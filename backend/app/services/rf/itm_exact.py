"""Exact reference propagation models: NTIA ITM (Longley-Rice) + ITU-R P.1812.

Two *reference-grade* engines alongside the in-house models:

ITM (Longley-Rice) — via ``itmlogic``, the peer-reviewed (JOSS) Python port of
the NTIA Irregular Terrain Model v1.2.2. The wrapper below follows the
project's published point-to-point recipe verbatim, and our test suite pins the
published validation case (the 77.8 km Crystal Palace profile at 41.5 MHz) to
its published expected losses within 0.1 dB — this is the *exact* algorithm,
not an approximation.

ITU-R P.1812 — via ``Py1812``, the official ITU-R Study Group 3 reference
implementation (v6, eeveetza/Py1812), with the ITU digital refractivity maps
(DN50/N050) installed from the official R-REC-P.1812 package. Valid 30 MHz–
6 GHz, 0.25–3000 km. Its per-point clutter-height input ``R`` plugs directly
into the C1 WorldCover representative heights — the Recommendation's own
clutter mechanism fed by real 10 m land cover.

Use ``tools/fetch_itu_maps.py`` to (re)install the ITU digital maps on a new
deployment — they are ITU integral products and are not redistributed in this
repository.
"""
from __future__ import annotations

import math

import numpy as np


# --------------------------------------------------------------- NTIA ITM
def itm_p2p_loss(distances_m, elevations_m, h_tx_m: float, h_rx_m: float,
                 freq_mhz: float, reliability_pct: float = 50.0,
                 confidence_pct: float = 50.0, eps: float = 15.0,
                 sgm: float = 0.005, en0: float = 314.0,
                 climate: int = 5, polarization: int = 0) -> dict:
    """Point-to-point ITM loss over an equally-spaced terrain profile.

    Follows the itmlogic reference p2p recipe exactly (same prop-dict
    initialization, same free-space term ``8.685890·ln(2·wn·dist)``, same
    ``avar(z_time, 0, z_confidence)`` call).
    """
    from itmlogic.misc.qerfi import qerfi
    from itmlogic.preparatory_subroutines.qlrpfl import qlrpfl
    from itmlogic.statistics.avar import avar

    e = np.asarray(elevations_m, dtype=np.float64)
    d = np.asarray(distances_m, dtype=np.float64)
    n = e.size - 1
    if n < 2:
        raise ValueError("profile needs at least 3 samples")
    span_m = float(d[-1] - d[0])

    pfl = [n, span_m / n]
    pfl.extend(float(x) for x in e)

    prop: dict = {
        "eps": eps, "sgm": sgm, "ipol": polarization,
        "fmhz": float(freq_mhz), "hg": [float(h_tx_m), float(h_rx_m)],
        "klim": int(climate), "ens0": float(en0),
        "lvar": 5, "gma": 157e-9, "kwx": 0,
        "klimx": 0, "mdvarx": 11,
        "pfl": pfl,
    }
    prop["wn"] = prop["fmhz"] / 47.7
    prop["ens"] = prop["ens0"]
    prop["gme"] = prop["gma"] * (1 - 0.04665 * math.exp(prop["ens"] / 179.3))
    zq = complex(prop["eps"], 376.62 * prop["sgm"] / prop["wn"])
    prop["zgnd"] = np.sqrt(zq - 1)
    if prop["ipol"] != 0:
        prop["zgnd"] = prop["zgnd"] / zq

    prop = qlrpfl(prop)

    fs_db = 8.685890 * math.log(2 * prop["wn"] * prop["dist"])
    zr = qerfi([reliability_pct / 100.0])[0]
    zc = qerfi([confidence_pct / 100.0])[0]
    avar1, prop = avar(zr, 0.0, zc, prop)
    total = fs_db + avar1

    return {
        "engine": "ntia_itm_1.2.2",
        "path_loss_db": round(float(total), 4),
        "free_space_db": round(float(fs_db), 4),
        "variability_plus_ref_db": round(float(avar1), 4),
        "reference_attenuation_db": round(float(prop.get("aref", 0.0)), 4),
        "terrain_dh_m": round(float(prop.get("dh", 0.0)), 2),
        "effective_heights_m": [round(float(h), 2) for h in prop.get("he", [])],
        "horizon_distances_m": [round(float(x), 1) for x in prop.get("dl", [])],
        "reliability_pct": reliability_pct,
        "confidence_pct": confidence_pct,
        "error_flag_kwx": int(prop.get("kwx", 0)),
    }


# ------------------------------------------------------------ ITU-R P.1812
def p1812_available() -> bool:
    try:
        from Py1812 import P1812  # noqa: F401
        return True
    except Exception:
        return False


def p452_available() -> bool:
    try:
        from Py452 import P452  # noqa: F401
        return True
    except Exception:
        return False


def p452_loss(distances_m, elevations_m, lats, lons,
              h_tx_m: float, h_rx_m: float, freq_mhz: float,
              time_pct: float = 50.0, clutter_heights_m=None,
              gt_dbi: float = 0.0, gr_dbi: float = 0.0,
              polarization: int = 1, dct_km: float = 500.0,
              dcr_km: float = 500.0, pressure_hpa: float = 1013.25,
              temp_c: float = 15.0) -> dict:
    """Interference basic transmission loss per the official ITU-R P.452-18
    reference code (clear-air interference coordination between stations on
    the Earth's surface, 0.1-50 GHz).

    ``time_pct`` is the percentage of time the loss is NOT exceeded — small
    values (e.g. 0.01 %) model rare ducting enhancements, the worst case for
    interference. ``clutter_heights_m`` feeds the Recommendation's own
    clutter input g = h + representative height (WorldCover per-pixel).
    ``dct_km``/``dcr_km`` are distances to the coast (500 = deep inland).
    """
    from Py452 import P452

    d_km = np.asarray(distances_m, dtype=np.float64) / 1000.0
    h = np.asarray(elevations_m, dtype=np.float64)
    lats = np.asarray(lats, dtype=np.float64)
    lons = np.asarray(lons, dtype=np.float64)
    f_ghz = freq_mhz / 1000.0
    if not (0.1 <= f_ghz <= 50.0):
        raise ValueError("P.452 is defined for 0.1 - 50 GHz")
    if not (0.001 <= time_pct <= 50.0):
        raise ValueError("P.452 time percentage must be in [0.001, 50] %")

    clutter = (np.asarray(clutter_heights_m, dtype=np.float64)
               if clutter_heights_m is not None else np.zeros_like(h))
    g = h + clutter                                  # Rec.'s clutter input
    zone = np.full(h.shape, 2, dtype=int)            # inland (no sea mask yet)

    lb = P452.bt_loss(f_ghz, float(time_pct), d_km, h, g, zone,
                      float(h_tx_m), float(h_rx_m),
                      float(lons[0]), float(lats[0]),
                      float(lons[-1]), float(lats[-1]),
                      float(gt_dbi), float(gr_dbi), int(polarization),
                      float(dct_km), float(dcr_km),
                      float(pressure_hpa), float(temp_c))
    lb = float(np.atleast_1d(lb)[0])
    fs = 32.45 + 20 * math.log10(freq_mhz) + 20 * math.log10(max(d_km[-1], 1e-3))
    return {
        "engine": "itu_p452_18_official",
        "path_loss_db": round(lb, 2),
        "free_space_db": round(fs, 2),
        "excess_over_fs_db": round(lb - fs, 2),
        "time_pct": time_pct,
        "clutter_applied": bool(clutter_heights_m is not None),
    }


def p1812_loss(distances_m, elevations_m, lats, lons,
               h_tx_m: float, h_rx_m: float, freq_mhz: float,
               time_pct: float = 50.0, location_pct: float = 50.0,
               clutter_heights_m=None, polarization: int = 1) -> dict:
    """Basic transmission loss per the official ITU-R P.1812 reference code.

    ``clutter_heights_m`` (optional, per profile point) feeds the
    Recommendation's own representative-clutter input ``R`` — pass the
    WorldCover heights from C1 for real per-pixel clutter.
    """
    from Py1812 import P1812

    d_km = np.asarray(distances_m, dtype=np.float64) / 1000.0
    h = np.asarray(elevations_m, dtype=np.float64)
    lats = np.asarray(lats, dtype=np.float64)
    lons = np.asarray(lons, dtype=np.float64)
    f_ghz = freq_mhz / 1000.0
    if not (0.03 <= f_ghz <= 6.0):
        raise ValueError("P.1812 is defined for 30 MHz - 6 GHz")

    R = (np.asarray(clutter_heights_m, dtype=np.float64)
         if clutter_heights_m is not None else np.zeros_like(h))
    zone = np.full(h.shape, 4, dtype=int)          # inland (no sea mask yet)

    lb = P1812.bt_loss(f_ghz, float(time_pct), d_km, h, R, zone,
                       float(h_tx_m), float(h_rx_m), int(polarization),
                       float(lats[0]), float(lats[-1]),
                       float(lons[0]), float(lons[-1]),
                       pL=float(location_pct))
    lb = float(np.atleast_1d(lb)[0])
    fs = 32.45 + 20 * math.log10(freq_mhz) + 20 * math.log10(max(d_km[-1], 1e-3))
    return {
        "engine": "itu_p1812_official",
        "path_loss_db": round(lb, 2),
        "free_space_db": round(fs, 2),
        "excess_over_fs_db": round(lb - fs, 2),
        "time_pct": time_pct, "location_pct": location_pct,
        "clutter_applied": bool(clutter_heights_m is not None),
    }
