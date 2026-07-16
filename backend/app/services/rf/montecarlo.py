"""Monte Carlo traffic snapshot simulation over a site cluster.

The deterministic capacity map (C4) answers "what rate does each pixel get
at full airtime". This module answers the operator question behind it:
*with U users dropped at random over the served area, what fraction gets the
rate it needs, and how loaded is each cell* — distributionally, over many
random snapshots, the way Atoll-class tools run traffic simulations (at
private-network scale, not national scale).

Method per draw:
  1. Drop ``users`` uniformly over the served pixels of the best-server
     composite (uniform-over-area is the standard null hypothesis for a
     demand layer; a weighted demand map can be added later).
  2. Each user attaches to the pixel's best server; per-pixel full-airtime
     rate comes from the same SINR -> CQI ladder as the capacity map.
  3. Equal-airtime scheduler within each cell: a user's rate is the pixel
     rate divided by the number of users in its cell that snapshot.
  4. A user is *satisfied* when that rate meets ``demand_mbps``.

Aggregates over ``draws`` snapshots (seeded, reproducible): mean/percentile
satisfied fraction, per-cell mean load and satisfaction — the saturation
verdict with confidence bounds instead of a single number.
"""
from __future__ import annotations

import numpy as np

from .capacity import throughput_map_mbps
from .freqplan import build_fields

MAX_DRAWS = 500
MAX_USERS = 5000


def _per_pixel_rate(fields: np.ndarray, best: np.ndarray, covered: np.ndarray,
                    noise_dbm: float, bandwidth_mhz: float, overhead: float,
                    channels: list[int] | None, aci_db: float) -> np.ndarray:
    """Full-airtime rate of every served pixel under its best server."""
    n = fields.shape[0]
    lin = np.where(np.isfinite(fields), 10.0 ** (fields / 10.0), 0.0)
    n_lin = 10.0 ** (noise_dbm / 10.0)
    aci = 10.0 ** (-aci_db / 10.0)
    idx = np.clip(best, 0, n - 1)
    s = np.take_along_axis(lin, idx[None, ...], axis=0)[0]
    interf = np.zeros_like(s)
    for j in range(n):
        other = lin[j] * (best != j)
        if channels is None:
            interf += other
        else:
            diff = np.abs(np.asarray(channels)[idx] - channels[j])
            interf += other * np.where(diff == 0, 1.0,
                                       np.where(diff == 1, aci, 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        sinr_db = 10.0 * np.log10(np.maximum(s, 1e-30) / (interf + n_lin))
    rate = throughput_map_mbps(sinr_db, bandwidth_mhz, overhead)
    return np.where(covered, rate, 0.0)


def simulate_traffic(computed: list[dict], users: int, demand_mbps: float,
                     noise_dbm: float, bandwidth_mhz: float,
                     draws: int = 100, overhead: float = 0.25,
                     channels: list[int] | None = None, aci_db: float = 30.0,
                     grid_n: int = 128, seed: int = 1) -> dict:
    """Monte Carlo traffic snapshots over a computed site cluster."""
    if not (1 <= draws <= MAX_DRAWS):
        raise ValueError(f"draws must be in [1, {MAX_DRAWS}]")
    if not (1 <= users <= MAX_USERS):
        raise ValueError(f"users must be in [1, {MAX_USERS}]")
    if demand_mbps <= 0:
        raise ValueError("demand_mbps must be positive")

    fields, best, covered = build_fields(computed, grid_n=grid_n)
    rate = _per_pixel_rate(fields, best, covered, noise_dbm, bandwidth_mhz,
                           overhead, channels, aci_db)
    served = covered & (rate > 0)
    pix = np.argwhere(served)
    if pix.size == 0:
        raise ValueError("no served pixels — nothing to simulate")
    pix_rate = rate[served]
    pix_cell = best[served]
    n_cells = len(computed)

    rng = np.random.default_rng(seed)
    sat_frac = np.empty(draws)
    user_rates_p5 = np.empty(draws)
    cell_users = np.zeros((draws, n_cells))
    cell_sat = np.zeros((draws, n_cells))

    for k in range(draws):
        pick = rng.integers(0, pix_rate.size, size=users)
        cells = pix_cell[pick]
        counts = np.bincount(cells, minlength=n_cells)
        per_user = pix_rate[pick] / np.maximum(counts[cells], 1)
        ok = per_user >= demand_mbps
        sat_frac[k] = ok.mean()
        user_rates_p5[k] = float(np.percentile(per_user, 5))
        cell_users[k] = counts
        # Per-cell satisfaction (cells with no users that draw count as NaN).
        for c in range(n_cells):
            m = cells == c
            cell_sat[k, c] = ok[m].mean() if m.any() else np.nan

    cells_out = []
    with np.errstate(invalid="ignore"):
        mean_cell_sat = np.nanmean(cell_sat, axis=0)
    for c in range(n_cells):
        cells_out.append({
            "site": computed[c].get("name") or f"Site {c + 1}",
            "mean_users": round(float(cell_users[:, c].mean()), 1),
            "mean_satisfied_fraction":
                round(float(mean_cell_sat[c]), 4)
                if np.isfinite(mean_cell_sat[c]) else None,
        })

    return {
        "method": "Monte Carlo traffic snapshots: uniform user drops over "
                  "served area, best-server attachment, equal-airtime "
                  "scheduler, SINR->CQI rates (3GPP 38.214 ladder)",
        "draws": draws, "users": users, "demand_mbps": demand_mbps,
        "seed": seed,
        "satisfied_fraction": {
            "mean": round(float(sat_frac.mean()), 4),
            "p5": round(float(np.percentile(sat_frac, 5)), 4),
            "p95": round(float(np.percentile(sat_frac, 95)), 4),
        },
        "user_rate_p5_mbps": {
            "mean": round(float(user_rates_p5.mean()), 2),
            "worst_draw": round(float(user_rates_p5.min()), 2),
        },
        "cells": cells_out,
        "plan_applied": channels is not None,
    }
