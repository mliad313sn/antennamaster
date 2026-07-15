"""Irregular Terrain Model (Longley-Rice family), point-to-point mode.

The one capability the reference tools (SPLAT!, Radio Mobile, commercial
suites) held over this app: a terrain-statistics propagation model that
delivers a *reliability quantile*, not just a median.  "Will 95% of locations,
50% of the time, have coverage?" is the question ITM answers and an empirical
Hata curve cannot.

This model combines three pieces, each either reused-and-validated or anchored
on an exact checkable value:

  * FREE SPACE + TERRAIN DIFFRACTION -- the median reference loss uses the
    codebase's already-validated Deygout multi-knife-edge diffraction over the
    k-curved fused profile (see ``models.deygout_loss_db``), so ITM's median is
    consistent with every other study in the app;
  * TERRAIN IRREGULARITY ``dh`` -- the Longley-Rice interdecile roughness (the
    10-to-90 percentile spread of the terrain about the path), which drives an
    excess-loss term and the fading spread;
  * VARIABILITY (avar) -- the ITM time / location / situation quantiles via the
    standard normal deviate ``qerfi`` (qerfi(0.5) = 0), so a higher requested
    reliability correctly costs more margin.

The knife-edge and normal-deviate sub-functions are faithful to the NTIA ITM
(Hufford, "The ITS Irregular Terrain Model"); the assembly is a documented
engineering model, not a byte-exact NTIA port, and reduces to free space on a
short clear line-of-sight path.
"""
from __future__ import annotations

import numpy as np

from .models import deygout_loss_db
from .physics import apply_earth_curvature


def qerfi(q: float) -> float:
    """Inverse complementary cumulative normal: the deviate x exceeded by a
    fraction q of a standard-normal population.  qerfi(0.5) = 0, qerfi(<0.5)
    > 0.  Standard ITM rational approximation."""
    c0, c1, c2 = 2.515516698, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    x = 0.5 - q
    t = max(0.5 - abs(x), 1e-9)
    t = np.sqrt(-2.0 * np.log(t))
    v = t - ((c2 * t + c1) * t + c0) / (((d3 * t + d2) * t + d1) * t + 1.0)
    return float(-v if x < 0.0 else v)


def aknfe(v2: float) -> float:
    """Fresnel-Kirchhoff knife-edge attenuation (dB) from the squared
    diffraction parameter v2.  aknfe(0) = 6.02 dB, the grazing edge."""
    if v2 < 5.76:
        return 6.02 + 9.11 * np.sqrt(v2) - 1.27 * v2
    return 12.953 + 10.0 * np.log10(v2)


def terrain_dh_m(elevations_m: np.ndarray) -> float:
    """Longley-Rice interdecile terrain roughness ``dh`` (m): the 10-to-90
    percentile spread of the terrain about the straight path, so it measures
    roughness rather than the mean slope."""
    e = np.asarray(elevations_m, dtype=np.float64)
    n = e.size
    if n < 3:
        return 0.0
    x = np.arange(n)
    resid = e - np.polyval(np.polyfit(x, e, 1), x)
    return float(np.percentile(resid, 90) - np.percentile(resid, 10))


def _irregularity_excess_db(dh: float, freq_mhz: float, dist_km: float,
                            los_clear: bool) -> float:
    """Excess loss from terrain irregularity, growing with dh, frequency and
    distance; a clear line-of-sight path pays only a small clutter term while a
    rough obstructed path pays more.  A documented Longley-Rice-family term."""
    f_term = 0.5 * np.log10(max(freq_mhz, 30.0) / 100.0)
    base = (0.06 if los_clear else 0.12) * dh * (1.0 + f_term)
    return float(max(base * min(dist_km / 10.0 + 0.5, 3.0), 0.0))


def itm_point_to_point(distances_m: np.ndarray, elevations_m: np.ndarray,
                       h_tx_m: float, h_rx_m: float, freq_mhz: float,
                       reliability: float = 0.5, confidence: float = 0.5,
                       k: float = 4.0 / 3.0) -> dict:
    """Irregular-terrain path loss with a reliability quantile.

    ``reliability`` is the fraction of TIME and ``confidence`` the fraction of
    SITUATIONS the prediction must hold for (0..1; 0.5/0.5 = median).  Returns
    the median reference loss, the variability adjustment and the total.
    """
    d = np.asarray(distances_m, dtype=np.float64)
    e = np.asarray(elevations_m, dtype=np.float64)
    dist_m = float(d[-1])
    dist_km = dist_m / 1000.0
    freq = float(freq_mhz)

    fs = 32.45 + 20.0 * np.log10(freq) + 20.0 * np.log10(max(dist_km, 1e-3))
    curved = apply_earth_curvature(d, e, k=k)
    diff = float(deygout_loss_db(d, curved, h_tx_m, h_rx_m, freq))
    los_clear = diff < 6.5           # ~ grazing; below this the path is open

    dh = terrain_dh_m(e)
    excess = _irregularity_excess_db(dh, freq, dist_km, los_clear)
    aref = fs + diff + excess
    regime = "line_of_sight" if los_clear else "diffraction"

    # Variability: fading spread grows with roughness and distance; the
    # requested reliability & confidence quantiles add (or, below median,
    # subtract) margin.  qerfi(>0.5) is negative -> more loss for higher
    # reliability, which is the sign the ITM avar produces.
    sigma_db = 3.0 + 0.5 * np.sqrt(max(dh, 0.0) / 10.0) + 0.02 * dist_km
    zr, zc = qerfi(reliability), qerfi(confidence)
    var_adjust = -(zr + zc) * sigma_db
    total = aref + var_adjust

    return {
        "path_loss_db": round(float(total), 1),
        "reference_loss_db": round(float(aref), 1),
        "free_space_db": round(float(fs), 1),
        "diffraction_db": round(diff, 1),
        "irregularity_excess_db": round(excess, 1),
        "variability_db": round(float(var_adjust), 1),
        "regime": regime,
        "terrain_dh_m": round(dh, 1),
        "reliability": reliability,
        "confidence": confidence,
    }
