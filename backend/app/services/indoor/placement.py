"""Automated access-point / node placement over a floor plan.

The coverage engine answers "what is the coverage of *this* AP?".  A designer
needs the inverse -- iBwave's flagship question: "given this plan and a target,
how *many* APs, *where*, and on *which channel*?".  This module solves it by
reusing the same vectorized multi-wall path-loss model as the cost function, so
the placement is consistent with what the heatmap will later show.

METHOD
    * candidate APs on a coarse grid over the plan; demand points on a finer
      grid (optionally weighted by a per-area user density);
    * greedy maximum-coverage set cover -- repeatedly add the candidate that
      newly covers the most demand until the coverage target is met or the AP
      budget is exhausted (greedy set cover is within (1 - 1/e) of optimal and
      is what real WLAN planners' auto-placers use);
    * a CAPACITY floor -- users x per-user throughput / per-AP capacity -- so
      density, not just coverage, can drive the count (Wi-Fi 6/7 reality);
    * a CHANNEL plan by graph colouring on the AP interference graph;
    * a ROAMING check -- fraction of demand with a secondary AP above the
      roaming threshold (-67 dBm class) for seamless voice/video hand-off.
"""
from __future__ import annotations

import numpy as np

from .floorplan import WallSet
from .materials import material_loss_db

# Non-overlapping channel sets by band (the classic reuse groups).
CHANNEL_SETS = {
    "2.4GHz": [1, 6, 11],
    "5GHz": [36, 40, 44, 48, 149, 153, 157, 161],
    "6GHz": [1, 37, 53, 69, 85, 101, 117, 133, 149, 165, 181, 197],
}


def _fspl_db(d_m: np.ndarray, f_mhz: float) -> np.ndarray:
    return 32.44 + 20.0 * np.log10(np.maximum(d_m, 0.25) / 1000.0) \
        + 20.0 * np.log10(f_mhz)


def _loss_ap_to_points(walls: WallSet, per_wall_loss: np.ndarray,
                       ap: np.ndarray, pts: np.ndarray, freq_mhz: float,
                       unit_scale: float, dz_m: float) -> np.ndarray:
    """Path loss (dB) from one AP to every demand point: 3D FSPL + the sum of
    material losses of walls the straight AP->point ray crosses (COST-231
    multi-wall), fully vectorized over points."""
    r = pts - ap                                           # (N, 2)
    wall_loss = np.zeros(pts.shape[0])
    for i in range(walls.count):
        a = walls.p0[i]
        s = walls.p1[i] - a
        denom = r[:, 0] * s[1] - r[:, 1] * s[0]
        ok = np.abs(denom) > 1e-12
        qp = a - ap
        t = (qp[0] * s[1] - qp[1] * s[0]) / np.where(ok, denom, 1.0)
        u = (qp[0] * r[:, 1] - qp[1] * r[:, 0]) / np.where(ok, denom, 1.0)
        crossed = ok & (t > 0.0) & (t < 1.0) & (u >= 0.0) & (u <= 1.0)
        wall_loss += np.where(crossed, per_wall_loss[i], 0.0)
    d2d = np.hypot(r[:, 0], r[:, 1]) * unit_scale
    d3d = np.sqrt(d2d ** 2 + dz_m ** 2)
    return _fspl_db(d3d, freq_mhz) + wall_loss


def auto_place_aps(walls: WallSet, freq_mhz: float,
                   tx_power_dbm: float = 20.0, tx_gain_dbi: float = 3.0,
                   rx_gain_dbi: float = 0.0, losses_db: float = 0.0,
                   rx_sensitivity_dbm: float = -72.0,
                   target_margin_db: float = 0.0,
                   unit_scale: float = 1.0,
                   tx_height_m: float = 2.7, rx_height_m: float = 1.2,
                   coverage_target: float = 0.95, max_aps: int = 24,
                   candidate_grid: int = 8, demand_grid: int = 24,
                   band: str = "2.4GHz",
                   roaming_threshold_dbm: float = -67.0,
                   users_total: int = 0, throughput_per_user_mbps: float = 0.0,
                   ap_capacity_mbps: float = 600.0) -> dict:
    """Solve AP count/positions/channels for a coverage (+capacity) target.

    Returns the placed APs (position, channel, share of demand covered), the
    predicted coverage fraction, the capacity-driven floor and a roaming-ready
    fraction.  ``target_margin_db`` designs above bare sensitivity.
    """
    if walls.count:
        x0, y0, x1, y1 = walls.bbox()
        per_wall_loss = np.array([material_loss_db(m, freq_mhz)
                                  for m in walls.material])
    else:
        x0, y0, x1, y1 = 0.0, 0.0, 100.0, 100.0
        per_wall_loss = np.zeros(0)
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)

    # Demand points and candidate AP positions on interior grids.
    def _grid(n_long: int):
        if w >= h:
            nx, ny = n_long, max(int(n_long * h / w), 2)
        else:
            ny, nx = n_long, max(int(n_long * w / h), 2)
        gx = np.linspace(x0 + w / (2 * nx), x1 - w / (2 * nx), nx)
        gy = np.linspace(y0 + h / (2 * ny), y1 - h / (2 * ny), ny)
        mx, my = np.meshgrid(gx, gy)
        return np.column_stack([mx.ravel(), my.ravel()])

    demand = _grid(demand_grid)
    candidates = _grid(candidate_grid)
    dz = abs(tx_height_m - rx_height_m)

    # Coverage & roaming budgets as max allowable path loss.
    eirp = tx_power_dbm + tx_gain_dbi + rx_gain_dbi - losses_db
    cover_budget = eirp - (rx_sensitivity_dbm + target_margin_db)
    roam_budget = eirp - roaming_threshold_dbm

    # Precompute each candidate's covered demand mask (served + roaming).
    cand_cover, cand_roam = [], []
    for c in candidates:
        loss = _loss_ap_to_points(walls, per_wall_loss, c, demand, freq_mhz,
                                  unit_scale, dz)
        cand_cover.append(loss <= cover_budget)
        cand_roam.append(loss <= roam_budget)
    cand_cover = np.array(cand_cover)                       # (C, N) bool
    cand_roam = np.array(cand_roam)

    # Capacity floor: enough APs to carry the offered load.
    cap_floor = 0
    if users_total > 0 and throughput_per_user_mbps > 0 and ap_capacity_mbps > 0:
        cap_floor = int(np.ceil(users_total * throughput_per_user_mbps
                                / ap_capacity_mbps))

    n_demand = demand.shape[0]
    covered = np.zeros(n_demand, dtype=bool)
    chosen: list[int] = []
    while len(chosen) < max_aps:
        gains = (cand_cover & ~covered).sum(axis=1)
        gains[chosen] = -1                                  # no re-pick
        best = int(np.argmax(gains))
        if gains[best] <= 0:
            break
        chosen.append(best)
        covered |= cand_cover[best]
        frac = covered.mean()
        # Coverage target met -> keep going only to satisfy the capacity floor.
        if frac >= coverage_target and len(chosen) >= cap_floor:
            break
    # Top up to the capacity floor with the best residual-coverage candidates.
    while len(chosen) < cap_floor and len(chosen) < max_aps:
        gains = (cand_cover & ~covered).sum(axis=1)
        gains[chosen] = -1
        best = int(np.argmax(gains))
        chosen.append(best)
        covered |= cand_cover[best]

    aps = candidates[chosen]
    channels = _assign_channels(aps, unit_scale, CHANNEL_SETS.get(band, [1, 6, 11]))

    # Roaming: demand points reachable by >= 2 APs above the roaming threshold.
    if chosen:
        roam_counts = cand_roam[chosen].sum(axis=0)
        roaming_ready = float(np.mean(roam_counts >= 2))
    else:
        roaming_ready = 0.0

    ap_out = []
    running = np.zeros(n_demand, dtype=bool)
    for idx, ci in enumerate(chosen):
        newly = int((cand_cover[ci] & ~running).sum())
        running |= cand_cover[ci]
        ap_out.append({
            "x": round(float(candidates[ci][0]), 2),
            "y": round(float(candidates[ci][1]), 2),
            "channel": channels[idx],
            "covers_points": int(cand_cover[ci].sum()),
            "new_points": newly,
        })
    return {
        "access_points": ap_out,
        "ap_count": len(chosen),
        "coverage_fraction": round(float(covered.mean()), 4),
        "coverage_target": coverage_target,
        "capacity_floor_aps": cap_floor,
        "roaming_ready_fraction": round(roaming_ready, 4),
        "band": band,
        "channels_used": sorted(set(channels)),
        "demand_points": n_demand,
        "bounds_dxf": [x0, y0, x1, y1],
    }


def _assign_channels(aps: np.ndarray, unit_scale: float,
                     channels: list[int]) -> list[int]:
    """Greedy graph-colour channel assignment: neighbouring APs (closest few)
    get different channels to minimise co-channel overlap.

    Edges connect each AP to its nearest neighbours (within a reuse radius set
    by the median spacing); colouring picks, for each AP in decreasing-degree
    order, the channel least used by already-coloured neighbours."""
    n = len(aps)
    if n == 0:
        return []
    if n == 1:
        return [channels[0]]
    # Pairwise distances (drawing units -> metres).
    d = np.linalg.norm(aps[:, None, :] - aps[None, :, :], axis=2) * unit_scale
    np.fill_diagonal(d, np.inf)
    reuse_r = float(np.median(np.min(d, axis=1))) * 1.6     # neighbour radius
    adj = [np.where(d[i] <= reuse_r)[0].tolist() for i in range(n)]
    order = sorted(range(n), key=lambda i: len(adj[i]), reverse=True)
    colour = [-1] * n
    for i in order:
        used = {colour[j] for j in adj[i] if colour[j] >= 0}
        # Least-used channel among neighbours, breaking ties by channel order.
        counts = {c: 0 for c in range(len(channels))}
        for j in adj[i]:
            if colour[j] >= 0:
                counts[colour[j]] += 1
        pick = min(range(len(channels)),
                   key=lambda c: (c in used, counts[c], c))
        colour[i] = pick
    return [channels[c] for c in colour]
