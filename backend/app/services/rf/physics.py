"""RF physics helpers: 4/3-earth curvature, Fresnel zones, knife-edge loss.

Every Fresnel / line-of-sight computation in this module operates on the
*effective* elevation profile: the fused terrain with the earth-curvature
bulge for effective earth radius factor k (default 4/3, standard
refraction) already applied via `apply_earth_curvature`.
"""
from __future__ import annotations

import numpy as np

from ...config import EARTH_RADIUS_M, K_FACTOR_DEFAULT

C_LIGHT = 299_792_458.0  # m/s


def apply_earth_curvature(distances_m: np.ndarray, elevations_m: np.ndarray,
                          k: float = K_FACTOR_DEFAULT) -> np.ndarray:
    """Add the effective-earth bulge to a terrain profile.

    With the flat-earth / bulged-terrain convention, a point at along-path
    distance d1 from TX and d2 from RX is raised by

        bulge = d1 * d2 / (2 * k * R_earth)

    so that a straight TX-RX line on the chart corresponds to a true radio
    line of sight under standard refraction (k = 4/3).  This MUST be applied
    before any Fresnel-clearance or knife-edge evaluation.
    """
    d = np.asarray(distances_m, dtype=np.float64)
    e = np.asarray(elevations_m, dtype=np.float64)
    total = d[-1] - d[0]
    if total <= 0:
        return e.copy()
    d1 = d - d[0]
    d2 = total - d1
    bulge = (d1 * d2) / (2.0 * k * EARTH_RADIUS_M)
    return e + bulge


def fresnel_radius_m(d1_m: np.ndarray, d2_m: np.ndarray, freq_hz: float,
                     zone: int = 1) -> np.ndarray:
    """Radius of the n-th Fresnel zone at a point d1 from TX, d2 from RX."""
    lam = C_LIGHT / freq_hz
    d1 = np.asarray(d1_m, dtype=np.float64)
    d2 = np.asarray(d2_m, dtype=np.float64)
    total = d1 + d2
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.sqrt(zone * lam * d1 * d2 / np.where(total > 0, total, np.inf))
    return np.nan_to_num(r)


def knife_edge_loss_db(v: float) -> float:
    """ITU-R P.526 single knife-edge diffraction loss approximation (dB)."""
    if v <= -0.78:
        return 0.0
    return 6.9 + 20.0 * np.log10(np.sqrt((v - 0.1) ** 2 + 1.0) + v - 0.1)


def analyze_path(distances_m: np.ndarray, elevations_m: np.ndarray,
                 tx_height_m: float, rx_height_m: float, freq_mhz: float,
                 k: float = K_FACTOR_DEFAULT) -> dict:
    """Full link analysis over a fused terrain profile.

    The curvature bulge (k) is applied here, internally, so callers hand in
    the raw fused profile.  Returns per-sample arrays (curved terrain, LOS
    line, first Fresnel-zone lower edge) plus scalar clearance/diffraction
    results for the worst obstruction.
    """
    d = np.asarray(distances_m, dtype=np.float64)
    freq_hz = freq_mhz * 1e6

    # 1) Earth curvature FIRST - all subsequent geometry uses the bulged profile.
    terrain = apply_earth_curvature(d, elevations_m, k=k)

    # 2) Antenna endpoints sit on the curved terrain.
    tx_e = terrain[0] + tx_height_m
    rx_e = terrain[-1] + rx_height_m
    total = d[-1] - d[0] if d[-1] > d[0] else 1.0
    los = tx_e + (rx_e - tx_e) * (d - d[0]) / total

    # 3) First Fresnel zone lower boundary.
    d1 = d - d[0]
    d2 = total - d1
    f1 = fresnel_radius_m(d1, d2, freq_hz, zone=1)
    fresnel_lower = los - f1

    # 4) Worst obstruction: maximum diffraction parameter v along the path
    #    (interior samples only - endpoints are the antennas themselves).
    lam = C_LIGHT / freq_hz
    interior = slice(1, -1)
    h_obs = terrain[interior] - los[interior]          # + above LOS, - below
    with np.errstate(divide="ignore", invalid="ignore"):
        v_arr = h_obs * np.sqrt(2.0 / lam * (d1[interior] + d2[interior])
                                / (d1[interior] * d2[interior]))
    v_arr = np.nan_to_num(v_arr, nan=-np.inf)
    worst_i = int(np.argmax(v_arr)) + 1
    worst_v = float(v_arr[worst_i - 1])
    loss_db = float(knife_edge_loss_db(worst_v))

    clearance = los - terrain
    min_clear_i = int(np.argmin(clearance[interior])) + 1
    # Fraction of first-Fresnel-zone clearance at the tightest point (>= 0.6
    # is the classic "clear path" rule of thumb).
    f1_at = f1[min_clear_i] if f1[min_clear_i] > 0 else 1.0
    fresnel_clearance_ratio = float(clearance[min_clear_i] / f1_at)

    return {
        "terrain_curved_m": terrain,
        "los_m": los,
        "fresnel1_lower_m": fresnel_lower,
        "line_of_sight_clear": bool(np.all(clearance[interior] > 0)),
        "fresnel_clearance_ratio": fresnel_clearance_ratio,
        "worst_obstruction_index": worst_i,
        "worst_obstruction_v": worst_v,
        "knife_edge_loss_db": loss_db,
        "k_factor": k,
    }
