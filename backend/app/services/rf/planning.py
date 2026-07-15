"""Planning tools built on the profile/coverage engines.

BATCH RECEIVER QUALIFICATION (WISP / fixed-wireless workflow)
    Evaluate one TX against a list of subscriber/CPE locations in a single
    call: per-receiver fused profile, Deygout diffraction, environmental
    losses and margin verdict.  This is the "can I serve these 50
    addresses?" question that otherwise needs 50 manual profile runs.

ANTENNA HEIGHT OPTIMIZER
    Minimum TX (or RX) height that clears the path, by bisection on the
    already-computed fused profile.  Two criteria: bare line of sight and
    the classic microwave rule of 60% first-Fresnel clearance.

REFRACTION RELIABILITY (dual-k check)
    Standard microwave practice: a dependable link needs 100% F1 clearance
    at k = 4/3 *and* 60% F1 at k = 2/3 (sub-refraction worst case).  The
    check exposes both ratios and a verdict.

BEST-SITE SEARCH
    Rank an n x n candidate grid over an area by coarse served-area
    fraction — the "where should the mast go?" question.  Uses low-res
    polar sweeps so a 5x5 grid stays interactive.
"""
from __future__ import annotations

import numpy as np
from pyproj import Geod

from ..terrain.fusion import TerrainFusionService
from .environment import (clutter_loss_db, foliage_loss_db,
                          gaseous_attenuation_db_per_km, rain_loss_db)
from .models import deygout_loss_db, path_loss_db
from .physics import K_FACTOR_DEFAULT, analyze_path, apply_earth_curvature
from .technologies import effective_sensitivity_dbm

_GEOD = Geod(ellps="WGS84")


# ------------------------------------------------------------------ batch
def evaluate_receiver(fusion: TerrainFusionService, tech: dict,
                      lat1: float, lon1: float, lat2: float, lon2: float,
                      k: float = K_FACTOR_DEFAULT,
                      foliage_depth_m: float = 0.0,
                      rain_rate_mm_h: float = 0.0,
                      clutter_pct: float = 0.0,
                      samples: int | None = None,
                      grid=None, georef=None) -> dict:
    """One receiver's full link verdict against the TX in ``tech`` terms.

    ``tech`` must carry freq_mhz, model, environment, h_bs_m, h_ut_m and the
    budget fields.  Sample count auto-scales with distance (one sample per
    ~75 m, clamped 32..512) unless given explicitly.
    """
    _, _, dist_m = _GEOD.inv(lon1, lat1, lon2, lat2)
    if samples is None:
        samples = int(np.clip(dist_m / 75.0, 32, 512))
    prof = fusion.profile(lat1, lon1, lat2, lon2, n_samples=samples,
                          grid=grid, georef=georef)
    d, elev = prof.distances_m, prof.elevations_m
    freq = float(tech["freq_mhz"])
    h_bs, h_ut = float(tech["h_bs_m"]), float(tech["h_ut_m"])

    rf = analyze_path(d, elev, h_bs, h_ut, freq, k=k)
    pl, warnings = path_loss_db(tech["model"], np.maximum(d[-1:], 1.0), freq,
                                h_bs, h_ut, tech.get("environment", "urban"))
    curved = apply_earth_curvature(d, elev, k=k)
    diff = deygout_loss_db(d, curved, h_bs, h_ut, freq)

    env = foliage_loss_db(freq, foliage_depth_m)
    env += gaseous_attenuation_db_per_km(freq) * dist_m / 1000.0
    env += rain_loss_db(freq, dist_m, rain_rate_mm_h)
    if clutter_pct > 0:
        env += float(clutter_loss_db(freq, dist_m, clutter_pct))

    mimo = float(tech.get("mimo_gain_db", 0.0))
    rx_power = (float(tech["tx_power_dbm"]) + float(tech["tx_gain_dbi"])
                + float(tech["rx_gain_dbi"]) + mimo - float(tech["losses_db"])
                - float(pl[-1]) - diff - env)
    sens = effective_sensitivity_dbm(tech)
    margin = rx_power - sens
    return {
        "distance_m": round(float(dist_m), 1),
        "rx_power_dbm": round(rx_power, 1),
        "margin_db": round(margin, 1),
        "served": bool(margin >= 0.0),
        "los_clear": rf["line_of_sight_clear"],
        "fresnel_clearance_ratio": round(rf["fresnel_clearance_ratio"], 3),
        "path_loss_db": round(float(pl[-1]), 1),
        "diffraction_loss_db": round(diff, 1),
        "environment_loss_db": round(env, 1),
        "warnings": warnings,
    }


# --------------------------------------------------------- height optimizer
def _clearance_ok(d, elev, tx_h, rx_h, freq, k, criterion: str) -> bool:
    rf = analyze_path(d, elev, tx_h, rx_h, freq, k=k)
    if criterion == "los":
        return rf["line_of_sight_clear"]
    # "f1_60": at least 60% of the first Fresnel radius at the tightest point.
    return rf["line_of_sight_clear"] and rf["fresnel_clearance_ratio"] >= 0.6


def min_height_m(d: np.ndarray, elev: np.ndarray, freq_mhz: float,
                 fixed_other_m: float, optimize: str = "tx",
                 criterion: str = "f1_60", k: float = K_FACTOR_DEFAULT,
                 max_height_m: float = 120.0) -> float | None:
    """Smallest antenna height (0..max) satisfying the clearance criterion.

    ``optimize`` is "tx" or "rx"; the other end stays at ``fixed_other_m``.
    Returns None when even ``max_height_m`` does not clear the path.
    Clearance is monotonic in either endpoint height (raising an endpoint
    raises the whole LOS line), so bisection is exact here.
    """
    def ok(h: float) -> bool:
        tx_h, rx_h = (h, fixed_other_m) if optimize == "tx" \
            else (fixed_other_m, h)
        return _clearance_ok(d, elev, tx_h, rx_h, freq_mhz, k, criterion)

    if not ok(max_height_m):
        return None
    lo, hi = 0.0, max_height_m
    if ok(lo):
        return 0.0
    for _ in range(24):                       # ~7e-6 relative precision
        mid = 0.5 * (lo + hi)
        if ok(mid):
            hi = mid
        else:
            lo = mid
    return round(hi, 1)


# ------------------------------------------------------- refraction check
def refraction_reliability(d: np.ndarray, elev: np.ndarray,
                           tx_h: float, rx_h: float, freq_mhz: float) -> dict:
    """Dual-k microwave clearance test:
    100% F1 at k=4/3 (standard) AND 60% F1 at k=2/3 (sub-refraction)."""
    std = analyze_path(d, elev, tx_h, rx_h, freq_mhz, k=4.0 / 3.0)
    sub = analyze_path(d, elev, tx_h, rx_h, freq_mhz, k=2.0 / 3.0)
    ok_std = std["line_of_sight_clear"] and std["fresnel_clearance_ratio"] >= 1.0
    ok_sub = sub["line_of_sight_clear"] and sub["fresnel_clearance_ratio"] >= 0.6
    return {
        "f1_ratio_k43": round(std["fresnel_clearance_ratio"], 3),
        "f1_ratio_k23": round(sub["fresnel_clearance_ratio"], 3),
        "clear_k43_100pct_f1": bool(ok_std),
        "clear_k23_60pct_f1": bool(ok_sub),
        "reliable": bool(ok_std and ok_sub),
    }


# ----------------------------------------------------------- site search
def site_search(engine, tech: dict, south: float, west: float,
                north: float, east: float, grid_n: int = 5,
                radius_m: float = 8000.0,
                shadow_margin_db: float = 0.0,
                clutter_pct: float = 0.0,
                k: float = K_FACTOR_DEFAULT,
                grid=None, georef=None,
                n_radials: int = 36, n_steps: int = 24) -> list[dict]:
    """Rank an n x n candidate grid by coarse served-area fraction.

    ``engine`` is a CoverageEngine.  Coarse sweeps (36 x 24 default) keep a
    5x5 grid interactive; the winner should be re-run at full resolution.
    Returns all candidates sorted best-first.
    """
    lats = np.linspace(south, north, grid_n)
    lons = np.linspace(west, east, grid_n)
    results: list[dict] = []
    for la in lats:
        for lo in lons:
            polar = engine.compute_polar(
                float(la), float(lo), dict(tech), radius_m=radius_m,
                n_radials=n_radials, n_steps=n_steps,
                shadow_margin_db=shadow_margin_db,
                clutter_pct=clutter_pct,
                k=k, grid=grid, georef=georef)
            w = polar["dist_g"] / polar["dist_g"].sum()
            served = float(np.sum((polar["margin"] >= 0.0) * w))
            results.append({
                "lat": round(float(la), 6), "lon": round(float(lo), 6),
                "served_area_fraction": round(served, 4),
                "tx_elevation_m": round(polar["tx_elev"], 1),
            })
    results.sort(key=lambda r: r["served_area_fraction"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1
    return results
