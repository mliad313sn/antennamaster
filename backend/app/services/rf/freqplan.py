"""Automatic frequency / PCI planning over a multi-site cluster.

Closes the "reuse-1 worst case only" gap: instead of assuming every site
transmits co-channel, this module *plans* the channels (and 5G/LTE Physical
Cell IDs) and then recomputes the SINR the plan actually delivers.

Pipeline:
  1. SHARED GRID — every site's polar field is resampled onto one geographic
     grid over the union bounding box (vectorized az/dist lookup per site).
  2. INTERFERENCE MATRIX — I[i][j] = mean linear power site j lands on the
     pixels where site i is the best server: the real, geometry-derived
     coupling between the cells (not adjacency guesswork).
  3. CHANNEL ASSIGNMENT — greedy weighted graph colouring (highest total
     coupling first, pick the channel minimising co-channel coupling plus an
     ACIR-discounted adjacent-channel term).
  4. PCI ASSIGNMENT — same greedy, penalising mod-3 collisions (and lightly
     mod-30) between strongly coupled neighbours, PCI 0..503.
  5. POST-PLAN SINR — per pixel: best server over interferers on the same
     channel (full power) and adjacent channels (attenuated by ACIR), thermal
     floor included; reported against the reuse-1 baseline so the gain of the
     plan is explicit.
"""
from __future__ import annotations

import numpy as np
from pyproj import Geod

_GEOD = Geod(ellps="WGS84")

PCI_MAX = 504


def _resample_to_grid(site: dict, glats: np.ndarray, glons: np.ndarray) -> np.ndarray:
    """Nearest-neighbour sample of one site's polar rx field (dBm) onto the
    shared grid; -inf where outside the site's simulated radius."""
    polar = site["polar"]
    az_step = 360.0 / polar["az"].shape[0]
    d = polar["dist"]
    d_step = d[1] - d[0] if d.shape[0] > 1 else d[0]

    az12, _az21, dist = _GEOD.inv(
        np.full(glons.shape, site["lon"]), np.full(glats.shape, site["lat"]),
        glons, glats)
    az_idx = np.mod(np.round(az12 / az_step).astype(int), polar["az"].shape[0])
    d_idx = np.round((dist - d[0]) / d_step).astype(int)
    ok = (d_idx >= 0) & (d_idx < d.shape[0])
    out = np.full(glats.shape, -np.inf)
    out[ok] = polar["rx_power"][az_idx[ok], d_idx[ok]]
    return out


def build_fields(computed: list[dict], grid_n: int = 128):
    """Shared-grid rx fields (n_sites, grid_n, grid_n) + best-server map."""
    lats = [s["lat"] for s in computed]
    lons = [s["lon"] for s in computed]
    r_deg = max(s["radius_m"] for s in computed) / 111_000.0
    south, north = min(lats) - r_deg, max(lats) + r_deg
    west, east = min(lons) - r_deg, max(lons) + r_deg
    gy = np.linspace(south, north, grid_n)
    gx = np.linspace(west, east, grid_n)
    glon, glat = np.meshgrid(gx, gy)
    fields = np.stack([_resample_to_grid(s, glat.ravel(), glon.ravel())
                       .reshape(grid_n, grid_n) for s in computed])
    best = np.argmax(fields, axis=0)
    covered = np.max(fields, axis=0) > -np.inf
    return fields, best, covered


def interference_matrix(fields: np.ndarray, best: np.ndarray,
                        covered: np.ndarray) -> np.ndarray:
    """I[i][j]: mean linear (mW) power site j delivers over site i's serving
    area — the coupling that decides whether i and j may share a channel."""
    n = fields.shape[0]
    lin = np.where(np.isfinite(fields), 10.0 ** (fields / 10.0), 0.0)
    I = np.zeros((n, n))
    for i in range(n):
        m = (best == i) & covered
        if not m.any():
            continue
        for j in range(n):
            if j != i:
                I[i, j] = float(lin[j][m].mean())
    return I


def assign_channels(I: np.ndarray, n_channels: int,
                    aci_db: float = 30.0) -> list[int]:
    """Greedy weighted colouring: strongest total coupling first; each site
    takes the channel minimising received co-channel coupling plus the
    ACIR-attenuated adjacent-channel term."""
    n = I.shape[0]
    w = I + I.T                                  # symmetric coupling
    order = np.argsort(-w.sum(axis=1))
    chan = [-1] * n
    aci = 10.0 ** (-aci_db / 10.0)
    for i in order:
        costs = np.zeros(n_channels)
        for j in range(n):
            if chan[j] >= 0 and j != i:
                for c in range(n_channels):
                    if chan[j] == c:
                        costs[c] += w[i, j]
                    elif abs(chan[j] - c) == 1:
                        costs[c] += w[i, j] * aci
        chan[i] = int(np.argmin(costs))
    return chan


def assign_pci(I: np.ndarray, chan: list[int]) -> list[int]:
    """PCI per site: avoid mod-3 collisions (primary sync interference) and
    lightly mod-30 collisions among coupled co-channel neighbours."""
    n = I.shape[0]
    w = I + I.T
    order = np.argsort(-w.sum(axis=1))
    pci = [-1] * n
    for i in order:
        best_pci, best_cost = 0, np.inf
        for cand in range(PCI_MAX):
            cost = 0.0
            for j in range(n):
                if pci[j] >= 0 and j != i and chan[j] == chan[i]:
                    if cand % 3 == pci[j] % 3:
                        cost += w[i, j]
                    if cand % 30 == pci[j] % 30:
                        cost += 0.3 * w[i, j]
            if cost < best_cost - 1e-18:
                best_cost, best_pci = cost, cand
            if best_cost == 0.0:
                break
        pci[i] = best_pci
    return pci


def sinr_stats(fields: np.ndarray, best: np.ndarray, covered: np.ndarray,
               chan: list[int] | None, noise_dbm: float,
               aci_db: float = 30.0) -> dict:
    """Per-pixel SINR with a channel plan (None = reuse-1 baseline)."""
    n = fields.shape[0]
    lin = np.where(np.isfinite(fields), 10.0 ** (fields / 10.0), 0.0)
    noise = 10.0 ** (noise_dbm / 10.0)
    aci = 10.0 ** (-aci_db / 10.0)
    S = np.zeros(best.shape)
    Itot = np.zeros(best.shape)
    for i in range(n):
        m = best == i
        S[m] = lin[i][m]
        for j in range(n):
            if j == i:
                continue
            if chan is None or chan[j] == chan[i]:
                Itot[m] += lin[j][m]
            elif abs(chan[j] - chan[i]) == 1:
                Itot[m] += lin[j][m] * aci
    with np.errstate(divide="ignore", invalid="ignore"):
        sinr_db = 10.0 * np.log10(S / (Itot + noise))
    v = sinr_db[covered & np.isfinite(sinr_db)]
    if v.size == 0:
        return {"mean_sinr_db": None, "pct_ge_6db": None, "cell_edge_pct": None}
    return {"mean_sinr_db": round(float(v.mean()), 2),
            "pct_ge_6db": round(float((v >= 6.0).mean() * 100.0), 1),
            "cell_edge_pct": round(float((v < 0.0).mean() * 100.0), 1)}


def plan_frequencies(computed: list[dict], n_channels: int,
                     noise_dbm: float, aci_db: float = 30.0,
                     with_pci: bool = True, grid_n: int = 128) -> dict:
    """Full plan: channels (+PCI) + before/after SINR statistics."""
    fields, best, covered = build_fields(computed, grid_n=grid_n)
    I = interference_matrix(fields, best, covered)
    chan = assign_channels(I, n_channels, aci_db=aci_db)
    pci = assign_pci(I, chan) if with_pci else None
    baseline = sinr_stats(fields, best, covered, None, noise_dbm, aci_db)
    planned = sinr_stats(fields, best, covered, chan, noise_dbm, aci_db)
    return {
        "assignments": [
            {"site": computed[i].get("name") or f"Site {i + 1}",
             "lat": computed[i]["lat"], "lon": computed[i]["lon"],
             "channel": chan[i],
             **({"pci": pci[i], "pci_mod3": pci[i] % 3} if pci else {})}
            for i in range(len(computed))],
        "n_channels": n_channels,
        "aci_db": aci_db,
        "sinr_reuse1_baseline": baseline,
        "sinr_after_plan": planned,
        "gain_mean_sinr_db": (round(planned["mean_sinr_db"]
                                    - baseline["mean_sinr_db"], 2)
                              if planned["mean_sinr_db"] is not None
                              and baseline["mean_sinr_db"] is not None else None),
    }
