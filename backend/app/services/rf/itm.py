"""Longley-Rice / ITM-family irregular-terrain propagation model.

An alternative to the Deygout knife-edge diffraction path, following the
Irregular Terrain Model's methodology: characterise the terrain by its
**interdecile height Δh** (the 10%-90% spread of terrain deviations from the
mean slope), split the path into the three Longley-Rice regimes by comparing
the path length to the sum of the two smooth-earth horizon distances, and
blend the appropriate reference attenuation:

* **Line-of-sight** (d ≤ d_horizon): free space + a terrain-roughness clutter
  term that grows with Δh and frequency.
* **Diffraction** (just beyond the horizon): free space + the actual profile's
  knife-edge diffraction + a rounded-earth excess that scales with Δh.
* **Troposcatter** (far beyond the horizon): a distance-growing scatter term.

This is an ITM-*family* implementation (Longley-Rice regime structure + Δh
terrain characterisation), not the exact NTIA reference FORTRAN; it gives the
irregular-terrain behaviour the reference tools use, as a selectable
alternative to Deygout.  It operates on the fused SRTM+DXF profile, so it
inherits the same terrain source as every other study.
"""
from __future__ import annotations

import numpy as np

from ...config import EARTH_RADIUS_M, K_FACTOR_DEFAULT
from .models import deygout_loss_db, fspl_db
from .physics import apply_earth_curvature


def interdecile_dh(distances_m: np.ndarray, elevations_m: np.ndarray) -> float:
    """Interdecile terrain-height Δh: the 10%-90% spread of terrain elevation
    residuals about the least-squares terrain slope (the Longley-Rice terrain
    irregularity parameter).  Δh ≈ 0 flat, ~90 m rolling hills, ~500 m rugged."""
    d = np.asarray(distances_m, dtype=np.float64)
    e = np.asarray(elevations_m, dtype=np.float64)
    if e.size < 3:
        return 0.0
    slope, intercept = np.polyfit(d, e, 1)
    resid = e - (slope * d + intercept)
    return float(np.percentile(resid, 90) - np.percentile(resid, 10))


def _horizon_distance_m(height_above_terrain_m: float, k: float) -> float:
    """Smooth-earth horizon distance for an antenna at the given height over
    the effective-earth surface: d = sqrt(2 * a * h), a = k * R_earth."""
    a = k * EARTH_RADIUS_M
    return float(np.sqrt(2.0 * a * max(height_above_terrain_m, 0.5)))


def itm_point_to_point(distances_m: np.ndarray, elevations_m: np.ndarray,
                       freq_mhz: float, h_tx_m: float, h_rx_m: float,
                       k: float = K_FACTOR_DEFAULT) -> dict:
    """ITM-family total path loss (dB) over a fused terrain profile.

    Returns the loss, the active propagation regime, Δh and the component
    breakdown, so the result is auditable against Deygout.
    """
    d = np.asarray(distances_m, dtype=np.float64)
    e = np.asarray(elevations_m, dtype=np.float64)
    total_m = float(d[-1] - d[0]) if d[-1] > d[0] else 1.0

    dh = interdecile_dh(d, e)
    fspl = float(fspl_db(np.array([total_m]), freq_mhz)[0])

    # Smooth-earth horizon distances from each antenna's height over terrain.
    d_ht = _horizon_distance_m(h_tx_m, k)
    d_hr = _horizon_distance_m(h_rx_m, k)
    d_horizon = d_ht + d_hr

    # Actual-profile knife-edge diffraction on the curved fused terrain.
    curved = apply_earth_curvature(d, e, k=k)
    knife = float(deygout_loss_db(d, curved, h_tx_m, h_rx_m, freq_mhz))

    # Terrain-roughness clutter (grows with Δh and frequency); always present.
    clutter = 0.05 * dh + 2.0 * np.log10(1.0 + freq_mhz / 100.0) * (1.0 + dh / 100.0)

    if total_m <= d_horizon:
        regime = "line_of_sight"
        # In LOS, diffraction is minor; roughness clutter dominates the excess.
        excess = clutter + 0.25 * knife
    elif total_m <= 1.5 * d_horizon:
        regime = "diffraction"
        excess = clutter + knife
    else:
        regime = "troposcatter"
        # Scatter excess grows with distance beyond 1.5x the horizon.
        beyond = (total_m - 1.5 * d_horizon) / 1000.0     # km beyond
        scatter = 0.4 * beyond + 10.0 * np.log10(1.0 + beyond)
        excess = clutter + knife + scatter

    loss = fspl + max(excess, 0.0)
    return {
        "model": "itm",
        "loss_db": round(float(loss), 1),
        "regime": regime,
        "dh_m": round(dh, 1),
        "free_space_db": round(fspl, 1),
        "knife_edge_db": round(knife, 1),
        "clutter_db": round(float(clutter), 1),
        "excess_db": round(float(max(excess, 0.0)), 1),
        "horizon_distance_m": round(d_horizon, 1),
        "path_distance_m": round(total_m, 1),
    }
