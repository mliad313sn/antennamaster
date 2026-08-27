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
                 climate: int = 5, polarization: int = 0,
                 mdvar: int = 11) -> dict:
    """Point-to-point ITM loss over an equally-spaced terrain profile.

    Follows the itmlogic reference p2p recipe exactly (same prop-dict
    initialization, same free-space term ``8.685890·ln(2·wn·dist)``, same
    ``avar(z_time, 0, z_confidence)`` call).

    ``mdvar`` selects ITM's mode of variability, and the default (11) is the
    point-to-point one: mode 1 with location variability *suppressed*, which
    is right here because both terminals sit at known fixed places — there is
    no population of receiver locations to be uncertain about. Area studies
    pass ``mdvar=2`` ("mobile") instead, where the receiver could be anywhere
    in the pixel and the quantile has to cover that; see ``itm_loss_grid``.
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
        "klimx": 0, "mdvarx": int(mdvar), "mdvar": int(mdvar),
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


def p2001_available() -> bool:
    try:
        from Py2001 import P2001  # noqa: F401
        return True
    except Exception:
        return False


def p2001_loss(distances_m, elevations_m, lats, lons,
               h_tx_m: float, h_rx_m: float, freq_mhz: float,
               time_pct: float = 50.0, gt_dbi: float = 0.0,
               gr_dbi: float = 0.0, polarization: int = 0) -> dict:
    """Basic transmission loss per the official ITU-R P.2001 reference code —
    the general-purpose wide-range model (30 MHz - 50 GHz, most accurate
    3 km - 1000+ km, full 0-100 % time range: fading AND enhancements in one
    model, the property that makes it the modern P.1546/P.452 unifier).
    """
    from Py2001 import P2001

    d_km = np.asarray(distances_m, dtype=np.float64) / 1000.0
    h = np.asarray(elevations_m, dtype=np.float64)
    lats = np.asarray(lats, dtype=np.float64)
    lons = np.asarray(lons, dtype=np.float64)
    f_ghz = freq_mhz / 1000.0
    if not (0.03 <= f_ghz <= 50.0):
        raise ValueError("P.2001 is defined for 30 MHz - 50 GHz")
    if not (0.00001 <= time_pct <= 99.99999):
        raise ValueError("P.2001 time percentage must be in (0, 100) %")

    zone = np.full(h.shape, 4, dtype=int)          # inland (no sea mask yet)
    lb = P2001.bt_loss(d_km, h, zone, f_ghz, float(time_pct),
                       float(lons[-1]), float(lats[-1]),
                       float(lons[0]), float(lats[0]),
                       float(h_rx_m), float(h_tx_m),
                       float(gr_dbi), float(gt_dbi), int(polarization))
    lb = float(np.atleast_1d(lb)[0])
    fs = 32.45 + 20 * math.log10(freq_mhz) + 20 * math.log10(max(d_km[-1], 1e-3))
    return {
        "engine": "itu_p2001_official",
        "path_loss_db": round(lb, 2),
        "free_space_db": round(fs, 2),
        "excess_over_fs_db": round(lb - fs, 2),
        "time_pct": time_pct,
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


# ------------------------------------------- ITM as an AREA coverage engine
# ITM's stated validity starts at 1 km (NTIA TN-101 / ITM v1.2.2); below it the
# algorithm sets kwx=4 rather than refusing, which would silently paint an
# out-of-range number over the busiest part of the map.
ITM_MIN_RANGE_M = 1000.0
def itm_loss_grid(elev: np.ndarray, dist: np.ndarray, tx_elev_m: float,
                  h_bs_m: float, h_ut_m: float, freq_mhz: float,
                  reliability_pct: float = 50.0,
                  confidence_pct: float = 50.0,
                  climate: int = 5, en0: float = 314.0,
                  eps: float = 15.0, sgm: float = 0.005,
                  polarization: int = 0, mdvar: int = 2,
                  progress_cb=None) -> tuple[np.ndarray, list[str]]:
    """Total path loss over a whole radial fan, one ITM run per sample.

    This is what makes ITM a *coverage* engine rather than a link tool. The
    empirical models the sweep otherwise uses (Hata, COST-231, TR 38.901) are
    fitted curves plus a separate Deygout diffraction term; ITM is the
    algorithm regulators and the incumbent tools (SPLAT!, Radio Mobile,
    TAP) actually run, and it derives the terrain effect itself. So the
    caller must NOT add a diffraction term on top: the number returned here
    already contains it, and adding Deygout would double-count the terrain.

    One run per (radial, range) sample, over the profile from the mast out to
    that sample — the same recipe as the point-to-point endpoint, which is
    exactly how SPLAT! builds a coverage plot. At 180x100 that is 18k runs
    and about 3 s; the profiles are short near the mast and grow outward, so
    the average run is far cheaper than the longest one.

    The variability mode is ITM's ``mdvar=2`` ("mobile"), NOT the
    point-to-point default. That is the substantive difference between a link
    study and a coverage study: point-to-point suppresses location
    variability because both terminals sit at known fixed places, whereas
    here the receiver could be anywhere in the pixel, and the quantile has to
    cover that. With location variability suppressed a 90% study came out
    0.7 dB below the median — a reliability knob that appears to work and
    does not. In mobile mode the same 90% costs ~12 dB, which is the number a
    coverage commitment is actually written on. The median is identical
    either way, so the pinned point-to-point validation is unaffected.

    ``elev`` is (radials, steps) ground elevation along each ray, ``dist``
    the (steps,) equally spaced ranges. Returns (loss_db, warnings).
    """
    from .models import fspl_db

    r, s = elev.shape
    step = float(dist[0])                      # rays start one step out
    out = np.empty((r, s), dtype=np.float64)
    warnings: list[str] = []
    if not 20.0 <= freq_mhz <= 20_000.0:
        warnings.append(
            f"ITM is specified for 20 MHz-20 GHz; {freq_mhz:g} MHz is outside "
            "that range and the result is an extrapolation.")

    kwx_seen = 0
    near_field = False
    for i in range(r):
        # The profile always starts AT the mast: the sweep's own samples
        # begin one step out, and ITM needs the transmitter's own ground
        # elevation to compute its horizon and effective height.
        ray = np.concatenate(([tx_elev_m], elev[i]))
        d_ray = np.concatenate(([0.0], dist))
        for j in range(s):
            # ITM is specified from 1 km out, and inside that it says so
            # (kwx=4) rather than refusing. Free space is the honest answer
            # there: at a few hundred metres from the mast the terrain term
            # is negligible, and it is what the incumbent tools fall back to.
            # It also guarantees the >=3 profile points the algorithm needs.
            if dist[j] < ITM_MIN_RANGE_M or j < 2:
                out[i, j] = float(fspl_db(np.array([dist[j]]), freq_mhz)[0])
                near_field = True
                continue
            res = itm_p2p_loss(d_ray[: j + 2], ray[: j + 2], h_bs_m, h_ut_m,
                               freq_mhz, reliability_pct=reliability_pct,
                               confidence_pct=confidence_pct, eps=eps,
                               sgm=sgm, en0=en0, climate=climate,
                               polarization=polarization, mdvar=mdvar)
            out[i, j] = res["path_loss_db"]
            kwx_seen = max(kwx_seen, res["error_flag_kwx"])
        if progress_cb is not None:
            progress_cb((i + 1) / r)
    if kwx_seen >= 3:
        # kwx 3 means ITM itself judged a parameter combination invalid, not
        # merely unusual. Saying so beats printing a number that looks like
        # every other number on the map.
        warnings.append(
            "ITM reported that some paths fall outside its valid parameter "
            "range (kwx=3); treat those areas as indicative only.")
    elif kwx_seen > 0:
        warnings.append(
            f"ITM flagged unusual parameters on some paths (kwx={kwx_seen}); "
            "results remain within the model's stated applicability.")
    if near_field:
        warnings.append(
            f"Inside {ITM_MIN_RANGE_M / 1000:g} km the study falls back to free "
            "space: ITM is specified from 1 km and reports its own parameter "
            "flag below that.")
    _ = step
    return out, warnings


# --------------------------------------- P.1812 as an AREA coverage engine
# P.1812's stated validity starts at 250 m (and runs to 3000 km). Below that
# the Recommendation simply does not apply, so the study says free space
# rather than extrapolating the official code outside its own range.
P1812_MIN_RANGE_M = 250.0
# The reference implementation refuses a profile of 4 points or fewer
# ("The number of points in path profile should be larger than 4",
# Py1812/P1812.py). The sweep's inner samples can produce exactly that, so
# the count is checked here rather than discovered as a ValueError out of a
# third-party library halfway through a study.
P1812_MIN_PROFILE_POINTS = 5


def p1812_loss_grid(elev: np.ndarray, dist: np.ndarray,
                    lats: np.ndarray, lons: np.ndarray,
                    tx_lat: float, tx_lon: float, tx_elev_m: float,
                    h_bs_m: float, h_ut_m: float, freq_mhz: float,
                    time_pct: float = 50.0, location_pct: float = 50.0,
                    clutter_heights: np.ndarray | None = None,
                    polarization: int = 1,
                    progress_cb=None) -> tuple[np.ndarray, list[str]]:
    """Total path loss over a whole radial fan, one P.1812 run per sample.

    Why this belongs next to the ITM area engine rather than replacing it:
    ITM is what the incumbent planning tools run, so a study made with it can
    be checked by a reviewer in their own tool; P.1812 is what a European
    regulator's own coordination is based on, so a study made with it is
    checkable against the Recommendation itself. A consultant wants both
    available, and wants to be told which one produced a given number.

    Two structural differences from the ITM grid, both of them substantive:

    * **Clutter is a separate input, not added to the ground.** The
      Recommendation takes representative clutter height as its own ``R``
      array alongside bare terrain; folding the canopy into ``h`` as well,
      the way our Deygout path legitimately does, would apply the same trees
      twice.
    * **The location percentage is a native parameter.** ITM needed the right
      variability mode to make its reliability quantile mean anything over an
      area; P.1812 takes ``pL`` directly, so "the level exceeded at 95% of
      locations" is the model's own statement rather than ours.

    Cost is about 0.5 ms per sample, so a default 180x100 sweep is roughly
    10 s - three to four times ITM and sixty times an empirical model. That
    is the price of the reference implementation, and it is why large sweeps
    on this engine belong on the queued (async) coverage path.

    ``elev`` is (radials, steps) BARE ground elevation along each ray;
    ``lats``/``lons`` the matching sample coordinates. Returns
    (loss_db, warnings).
    """
    from .models import fspl_db

    r, s = elev.shape
    out = np.empty((r, s), dtype=np.float64)
    warnings: list[str] = []
    if not 30.0 <= freq_mhz <= 6000.0:
        # The wrapper would raise; refusing the whole study for one preset is
        # worse than saying plainly which limit was hit.
        raise ValueError(
            f"ITU-R P.1812 is defined for 30 MHz - 6 GHz; {freq_mhz:g} MHz is "
            "outside it. Use ITM (20 MHz - 20 GHz) or an empirical model.")

    near_field = False
    d_ray = np.concatenate(([0.0], dist))
    for i in range(r):
        # Every profile starts AT the mast: the sweep's samples begin one step
        # out, and the Recommendation needs the transmitter's own ground
        # height and position to place its horizon.
        ray_h = np.concatenate(([tx_elev_m], elev[i]))
        ray_lat = np.concatenate(([tx_lat], lats[i]))
        ray_lon = np.concatenate(([tx_lon], lons[i]))
        ray_R = (np.concatenate(([0.0], clutter_heights[i]))
                 if clutter_heights is not None else None)
        for j in range(s):
            # Two independent preconditions, both from the Recommendation:
            # its 250 m lower range limit, and its minimum profile length
            # (the slice below is j + 2 points long).
            if (dist[j] < P1812_MIN_RANGE_M
                    or j + 2 < P1812_MIN_PROFILE_POINTS):
                out[i, j] = float(fspl_db(np.array([dist[j]]), freq_mhz)[0])
                near_field = True
                continue
            res = p1812_loss(
                d_ray[: j + 2], ray_h[: j + 2], ray_lat[: j + 2],
                ray_lon[: j + 2], h_bs_m, h_ut_m, freq_mhz,
                time_pct=time_pct, location_pct=location_pct,
                clutter_heights_m=None if ray_R is None else ray_R[: j + 2],
                polarization=polarization)
            out[i, j] = res["path_loss_db"]
        if progress_cb is not None:
            progress_cb((i + 1) / r)

    if near_field:
        warnings.append(
            f"Inside {P1812_MIN_RANGE_M:g} m the study falls back to free "
            "space: ITU-R P.1812 is defined from 250 m outwards.")
    if clutter_heights is not None:
        warnings.append(
            "Clutter was supplied to P.1812 as its own representative-height "
            "input R (the Recommendation's mechanism), not added to the "
            "terrain.")
    return out, warnings
