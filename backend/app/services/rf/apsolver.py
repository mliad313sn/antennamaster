"""Phase 3 — automated access-point / site placement solver.

Given a floor plan (or terrain) and a coverage/capacity target, this module
*solves* for the design a planner otherwise builds by hand: how many access
points, where to put them, and on which channel.

Pipeline:

1. **Discretize** the area into demand points (what must be covered) and a
   coarser candidate-position grid (where an AP may go).
2. **Predict** RSSI from every candidate to every demand point.  Indoor uses
   the vectorized COST-231 multi-wall model (same physics as the coverage
   heatmap); outdoor uses a distance path-loss model over the terrain.
3. **Greedy max-coverage** picks the fewest APs to reach the coverage target.
4. **Capacity sizing** adds APs if user density / throughput demand needs more
   cells than coverage alone (Wi-Fi 6/7 users-per-AP and per-AP throughput).
5. **Roaming** checks every demand point has a *second* AP above the roaming
   threshold (-67 dBm) for seamless hand-off.
6. **Channel plan** graph-colours the interference graph (Welsh-Powell) with
   the band's non-overlapping channels.

The greedy set-cover heuristic is the right tool here: AP placement is a
max-coverage / partial-set-cover problem, where greedy gives a provable
(1-1/e) approximation and stays interactive, unlike a genetic search.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .environment import thermal_sensitivity_dbm  # noqa: F401  (parity import)
from .models import path_loss_db
from .technologies import get_technology

C_LIGHT = 299_792_458.0

# Non-overlapping channel sets by band.
CHANNEL_PLANS: dict[str, list[int]] = {
    "2.4GHz": [1, 6, 11],
    "5GHz": [36, 40, 44, 48, 149, 153, 157, 161],
    "6GHz": [1, 37, 53, 69, 85, 101, 117, 133, 149, 165, 181, 197, 213, 229],
}

# Default users-per-AP association limits (practical, not the spec maximum).
WIFI_USERS_PER_AP = {"wifi5": 25, "wifi6": 40, "wifi6e": 50, "wifi7": 60}


# --------------------------------------------------------------------------- #
#  RSSI builders (candidate x demand matrices)
# --------------------------------------------------------------------------- #
def _multiwall_loss(walls, ap_xy: np.ndarray, points_xy: np.ndarray,
                    freq_mhz: float, unit_scale: float) -> np.ndarray:
    """Total wall-crossing loss (dB) from one AP to each demand point,
    vectorized ray/segment intersection — the engine's method, standalone."""
    from ..indoor.materials import material_loss_db  # noqa
    n = points_xy.shape[0]
    loss = np.zeros(n)
    if walls is None or walls.count == 0:
        return loss
    per_wall = np.array([material_loss_db(m, freq_mhz) for m in walls.material])
    p = np.asarray(ap_xy, dtype=np.float64)
    r = points_xy - p                                   # (N,2)
    for i in range(walls.count):
        a = walls.p0[i]
        s = walls.p1[i] - a
        denom = r[:, 0] * s[1] - r[:, 1] * s[0]
        ok = np.abs(denom) > 1e-12
        qp = a - p
        t = (qp[0] * s[1] - qp[1] * s[0]) / np.where(ok, denom, 1.0)
        u = (qp[0] * r[:, 1] - qp[1] * r[:, 0]) / np.where(ok, denom, 1.0)
        crossed = ok & (t > 0.0) & (t < 1.0) & (u >= 0.0) & (u <= 1.0)
        loss += np.where(crossed, per_wall[i], 0.0)
    return loss


def _fspl(d_m: np.ndarray, f_mhz: float) -> np.ndarray:
    return 32.44 + 20.0 * np.log10(np.maximum(d_m, 0.5) / 1000.0) + 20.0 * np.log10(f_mhz)


def build_indoor_rssi(walls, candidates: np.ndarray, demand: np.ndarray,
                      freq_mhz: float, unit_scale: float,
                      tx_power_dbm: float, tx_gain_dbi: float,
                      rx_gain_dbi: float = 0.0,
                      environment: str = "office") -> np.ndarray:
    """RSSI matrix (n_candidates, n_demand).

    Mirrors the coverage engine's model choice: with explicit walls the loss
    is FSPL + summed COST-231 wall crossings; with no wall geometry it falls
    back to the ITU-R P.1238 site-general indoor model (a realistic distance
    exponent, so open-plan range is finite rather than free-space-optimistic).
    """
    from ..indoor.engine import itu_p1238_loss_db
    has_walls = walls is not None and getattr(walls, "count", 0) > 0
    rssi = np.empty((candidates.shape[0], demand.shape[0]))
    for i, ap in enumerate(candidates):
        d_units = np.hypot(demand[:, 0] - ap[0], demand[:, 1] - ap[1])
        d_m = np.maximum(d_units * unit_scale, 0.5)
        if has_walls:
            loss = _fspl(d_m, freq_mhz) + _multiwall_loss(
                walls, ap, demand, freq_mhz, unit_scale)
        else:
            loss = itu_p1238_loss_db(d_m, freq_mhz, 0, environment)
        rssi[i] = tx_power_dbm + tx_gain_dbi + rx_gain_dbi - loss
    return rssi


def build_outdoor_rssi(candidates: np.ndarray, demand: np.ndarray,
                       tech: dict, unit_scale: float) -> np.ndarray:
    """RSSI matrix for an outdoor mesh: distance path-loss (no per-point
    terrain profile — a fast planning approximation for AP/small-cell grids).
    Coordinates are treated as a local metric plane (meters = units*scale)."""
    freq = float(tech["freq_mhz"])
    rssi = np.empty((candidates.shape[0], demand.shape[0]))
    for i, ap in enumerate(candidates):
        d_m = np.maximum(np.hypot(demand[:, 0] - ap[0], demand[:, 1] - ap[1])
                         * unit_scale, 1.0)
        pl, _ = path_loss_db(tech["model"], d_m, freq,
                             float(tech["h_bs_m"]), float(tech["h_ut_m"]),
                             tech.get("environment", "urban"))
        rssi[i] = (float(tech["tx_power_dbm"]) + float(tech["tx_gain_dbi"])
                   + float(tech["rx_gain_dbi"]) - float(tech.get("losses_db", 0.0))
                   - pl)
    return rssi


# --------------------------------------------------------------------------- #
#  Grids
# --------------------------------------------------------------------------- #
def make_grid(bbox: tuple[float, float, float, float], spacing_units: float,
              inset: float = 0.0) -> np.ndarray:
    """Regular point grid over a bbox in drawing units."""
    x0, y0, x1, y1 = bbox
    x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    nx = max(int(round((x1 - x0) / max(spacing_units, 1e-6))) + 1, 2)
    ny = max(int(round((y1 - y0) / max(spacing_units, 1e-6))) + 1, 2)
    gx = np.linspace(x0, x1, nx)
    gy = np.linspace(y0, y1, ny)
    mx, my = np.meshgrid(gx, gy)
    return np.column_stack([mx.ravel(), my.ravel()])


# --------------------------------------------------------------------------- #
#  Channel assignment (Welsh-Powell graph colouring)
# --------------------------------------------------------------------------- #
def assign_channels(adjacency: list[set[int]], channels: list[int]) -> dict:
    """Colour the interference graph so adjacent APs get different channels.
    Welsh-Powell: order vertices by descending degree, assign the lowest
    channel not used by an already-coloured neighbour; reuse (co-channel)
    only when the palette is exhausted."""
    n = len(adjacency)
    order = sorted(range(n), key=lambda v: len(adjacency[v]), reverse=True)
    color_idx = [-1] * n
    cochannel = 0
    for v in order:
        used = {color_idx[u] for u in adjacency[v] if color_idx[u] >= 0}
        c = 0
        while c < len(channels) and c in used:
            c += 1
        if c >= len(channels):        # palette exhausted -> forced reuse
            c = 0
            cochannel += 1
        color_idx[v] = c
    return {"channels": [channels[c] for c in color_idx],
            "channel_index": color_idx,
            "cochannel_conflicts": cochannel,
            "colors_used": len(set(color_idx))}


# --------------------------------------------------------------------------- #
#  The solver
# --------------------------------------------------------------------------- #
@dataclass
class ApSolution:
    aps: list[dict]
    ap_count: int
    coverage_fraction: float
    roaming_fraction: float
    capacity: dict
    channel_plan: dict
    demand_points: int
    warnings: list[str] = field(default_factory=list)


def solve_layout(rssi: np.ndarray, candidates: np.ndarray, demand: np.ndarray,
                 target_rssi_dbm: float,
                 target_coverage: float = 0.98,
                 roaming_threshold_dbm: float = -67.0,
                 max_aps: int = 40,
                 area_m2: float = 0.0,
                 user_density_per_100m2: float = 0.0,
                 users_per_ap: int = 40,
                 throughput_demand_mbps: float = 0.0,
                 ap_capacity_mbps: float = 600.0,
                 ceiling_z_m: float = 2.7,
                 channels: list[int] | None = None,
                 unit_scale: float = 1.0) -> ApSolution:
    """Greedy max-coverage placement + capacity sizing + roaming + channels.

    ``rssi`` is (n_candidates, n_demand).  Returns the chosen APs with x/y
    (drawing units), z (meters), channel and the served demand count.
    """
    warnings: list[str] = []
    covers = rssi >= target_rssi_dbm            # (C, D) boolean
    n_demand = demand.shape[0]

    # ---- 1) greedy coverage ------------------------------------------------
    uncovered = np.ones(n_demand, dtype=bool)
    chosen: list[int] = []
    target_count = math.ceil(target_coverage * n_demand)
    while uncovered.sum() > (n_demand - target_count) and len(chosen) < max_aps:
        gains = (covers & uncovered).sum(axis=1)
        gains[chosen] = -1                       # don't reuse a position
        best = int(np.argmax(gains))
        if gains[best] <= 0:
            warnings.append("Coverage target unreachable with the candidate "
                            "grid; add candidate positions or relax the target.")
            break
        chosen.append(best)
        uncovered &= ~covers[best]

    coverage_fraction = float(1.0 - uncovered.sum() / n_demand)

    # ---- 2) capacity sizing ------------------------------------------------
    total_users = user_density_per_100m2 * area_m2 / 100.0
    cap_by_users = math.ceil(total_users / users_per_ap) if users_per_ap > 0 else 0
    cap_by_tput = math.ceil(throughput_demand_mbps / ap_capacity_mbps) \
        if ap_capacity_mbps > 0 else 0
    capacity_aps = max(cap_by_users, cap_by_tput)
    if capacity_aps > len(chosen):
        # Add the best remaining candidates (most demand covered) to spread load.
        remaining = sorted((c for c in range(candidates.shape[0]) if c not in chosen),
                           key=lambda c: covers[c].sum(), reverse=True)
        for c in remaining[:capacity_aps - len(chosen)]:
            chosen.append(c)
        warnings.append(f"Capacity ({total_users:.0f} users / "
                        f"{throughput_demand_mbps:.0f} Mbps) required "
                        f"{capacity_aps} APs — added beyond coverage need.")

    if not chosen:
        return ApSolution([], 0, 0.0, 0.0,
                          {"capacity_aps": capacity_aps, "total_users": round(total_users)},
                          {"channels": [], "cochannel_conflicts": 0, "colors_used": 0},
                          n_demand, warnings + ["No AP positions chosen."])

    chosen_rssi = rssi[chosen]                   # (K, D)

    # ---- 3) roaming: every demand point needs a 2nd AP above threshold -----
    above_roam = chosen_rssi >= roaming_threshold_dbm
    second_ap = above_roam.sum(axis=0) >= 2
    roaming_fraction = float(second_ap.mean())

    # ---- 4) interference graph + channel colouring -------------------------
    k = len(chosen)
    adjacency: list[set[int]] = [set() for _ in range(k)]
    for a in range(k):
        for b in range(a + 1, k):
            # Two APs interfere if any demand point hears both above roaming.
            if np.any(above_roam[a] & above_roam[b]):
                adjacency[a].add(b)
                adjacency[b].add(a)
    plan = assign_channels(adjacency, channels or CHANNEL_PLANS["5GHz"])

    best_owner = np.argmax(chosen_rssi, axis=0)
    aps = []
    for j, ci in enumerate(chosen):
        served = int(((best_owner == j) & (chosen_rssi[j] >= target_rssi_dbm)).sum())
        aps.append({
            "index": j,
            "x": round(float(candidates[ci][0]), 3),
            "y": round(float(candidates[ci][1]), 3),
            "z_m": round(float(ceiling_z_m), 2),
            "channel": plan["channels"][j],
            "served_demand_points": served,
        })

    return ApSolution(
        aps=aps, ap_count=k,
        coverage_fraction=round(coverage_fraction, 4),
        roaming_fraction=round(roaming_fraction, 4),
        capacity={"total_users": round(total_users),
                  "cap_by_users": cap_by_users, "cap_by_throughput": cap_by_tput,
                  "capacity_aps": capacity_aps, "users_per_ap": users_per_ap,
                  "ap_capacity_mbps": ap_capacity_mbps},
        channel_plan=plan, demand_points=n_demand, warnings=warnings)
