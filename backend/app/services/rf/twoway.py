"""Two-way "talk-back" system design: repeater <-> portable <-> base station.

Prediction tools compute only the *downlink* (infrastructure -> user).  A
land-mobile-radio (LMR) system is limited by the WEAKER of two directions:

  * talk-out  (base/repeater -> portable) -- a high-power base into a small,
    body-shadowed handheld receiver;
  * talk-in   (portable -> base/repeater) -- a 1-5 W handheld into a sensitive
    base receiver.

The coverage a fleet actually experiences is the INTERSECTION of the two, and
every pixel is limited by one direction or the other.  This module computes
both and classifies the limiting direction.

RECIPROCITY (why this is cheap)
    Over one path at one frequency the path loss, diffraction, antenna pattern
    directivity and environmental losses are identical in both directions.
    The received powers therefore differ by a single constant::

        rx_talk_in - rx_talk_out = P_portable_tx - P_base_tx

    (both antenna peak gains appear in both budgets; body loss and building
    penetration sit on the path and subtract from both equally).  So a single
    downlink field yields the uplink field by adding one scalar -- no second
    propagation pass.

DAQ -- DELIVERED AUDIO QUALITY (TIA-4046 / TSB-88)
    Public-safety and mining LMR tenders are written in DAQ, not raw dBm:

        DAQ 1   unusable
        DAQ 2   understandable with considerable effort
        DAQ 3.0 understandable, occasional repetition
        DAQ 3.4 understandable, repetition rarely required  <-- common target
        DAQ 4.0 understandable without repetition
        DAQ 4.5 near perfect

    A rigorous DAQ prediction needs a faded bit-error / C/N model; for a
    planning tool we map delivered signal to DAQ against a *faded performance
    threshold* -- the signal level that yields DAQ 3.4 over the faded channel,
    taken as the static reference sensitivity plus a faded-performance margin
    (default 20 dB, the classic LMR figure for Rayleigh + lognormal at the
    design reliability).  The offsets below are a documented engineering
    heuristic, not a measured BER curve, and every anchor is overridable.

PORTABLE-RADIO REALISM
    A handheld is not a rooftop CPE: body loss (~3-6 dB), 1.5 m height and a
    penetration class (on-street / in-vehicle / in-building) dominate the real
    link and are modelled explicitly.
"""
from __future__ import annotations

import numpy as np
from pyproj import Geod

from ..terrain.fusion import TerrainFusionService
from .environment import (clutter_loss_db, foliage_loss_db,
                          gaseous_attenuation_db_per_km, rain_loss_db)
from .models import deygout_loss_db, path_loss_db
from .physics import K_FACTOR_DEFAULT, analyze_path, apply_earth_curvature

_GEOD = Geod(ellps="WGS84")

# Faded-performance margin over static reference sensitivity that defines the
# DAQ 3.4 anchor (dB).  Classic LMR value for the combined Rayleigh (fast) and
# lognormal (slow) fading at typical design reliability.
DEFAULT_FADED_MARGIN_DB = 20.0

# DAQ grade vs delivered signal offset from the DAQ 3.4 anchor (dB).  Ordered
# best-first; the first threshold the offset clears wins.  A documented
# planning heuristic (see module docstring), not a measured BER curve.
DAQ_OFFSETS = [
    (10.0, 4.5, "DAQ 4.5 - near perfect"),
    (6.0, 4.0, "DAQ 4.0 - understandable without repetition"),
    (0.0, 3.4, "DAQ 3.4 - repetition rarely required"),
    (-4.0, 3.0, "DAQ 3.0 - occasional repetition"),
    (-10.0, 2.0, "DAQ 2.0 - understandable with effort"),
]

# Penetration classes: excess loss the portable sees on top of the outdoor
# path, applied to BOTH directions (the loss is on the path, near the user).
PENETRATION_CLASSES = {
    "on_street": {"label": "On street / outdoors", "loss_db": 0.0},
    "in_vehicle": {"label": "Inside a vehicle", "loss_db": 8.0},
    "light_building": {"label": "Light building (wood/glass)", "loss_db": 12.0},
    "heavy_building": {"label": "Heavy building (concrete)", "loss_db": 20.0},
    "underground": {"label": "Basement / sub-level", "loss_db": 30.0},
}

DEFAULT_BODY_LOSS_DB = 4.0


def daq_grade(rx_dbm: float, sensitivity_dbm: float,
              faded_margin_db: float = DEFAULT_FADED_MARGIN_DB) -> dict:
    """Delivered-audio-quality grade for a received level.

    ``sensitivity_dbm`` is the static reference sensitivity; the DAQ 3.4 anchor
    sits ``faded_margin_db`` above it.  Returns the numeric grade, a label and
    the offset above the anchor.
    """
    anchor = sensitivity_dbm + faded_margin_db
    offset = rx_dbm - anchor
    for thr, grade, label in DAQ_OFFSETS:
        if offset >= thr:
            return {"daq": grade, "label": label,
                    "offset_db": round(float(offset), 1)}
    return {"daq": 1.0, "label": "DAQ 1 - unusable",
            "offset_db": round(float(offset), 1)}


def _penetration_db(portable: dict) -> float:
    """Total portable excess loss = body loss + penetration class."""
    body = float(portable.get("body_loss_db", DEFAULT_BODY_LOSS_DB))
    cls = portable.get("penetration_class", "on_street")
    pen = portable.get("penetration_db")
    if pen is None:
        pen = PENETRATION_CLASSES.get(cls, PENETRATION_CLASSES["on_street"])["loss_db"]
    return body + float(pen)


def _talkback_verdict(rx_out: float, rx_in: float,
                      portable_sens: float, base_sens: float,
                      target_daq: float, faded_margin_db: float) -> dict:
    """Both-direction DAQ + limiting-direction classification for one link."""
    out = daq_grade(rx_out, portable_sens, faded_margin_db)
    inb = daq_grade(rx_in, base_sens, faded_margin_db)
    margin_out = rx_out - (portable_sens + faded_margin_db)
    margin_in = rx_in - (base_sens + faded_margin_db)
    # The link "works" at the target when the weaker direction meets it.
    ok_out = out["daq"] >= target_daq
    ok_in = inb["daq"] >= target_daq
    limiting = "talk_in" if margin_in <= margin_out else "talk_out"
    return {
        "talk_out": {"rx_power_dbm": round(float(rx_out), 1),
                     "margin_db": round(float(margin_out), 1), **out},
        "talk_in": {"rx_power_dbm": round(float(rx_in), 1),
                    "margin_db": round(float(margin_in), 1), **inb},
        "limiting_direction": limiting,
        "worst_daq": min(out["daq"], inb["daq"]),
        "reliable": bool(ok_out and ok_in),
    }


def twoway_evaluate_receiver(fusion: TerrainFusionService,
                             base: dict, portable: dict,
                             lat1: float, lon1: float,
                             lat2: float, lon2: float,
                             target_daq: float = 3.4,
                             faded_margin_db: float = DEFAULT_FADED_MARGIN_DB,
                             k: float = K_FACTOR_DEFAULT,
                             foliage_depth_m: float = 0.0,
                             rain_rate_mm_h: float = 0.0,
                             clutter_pct: float = 0.0,
                             samples: int | None = None,
                             grid=None, georef=None) -> dict:
    """Bidirectional talk-back verdict for one base<->portable link.

    ``base`` carries freq_mhz, model, environment, h_bs_m, tx_power_dbm,
    ant_gain_dbi (used both ways by reciprocity), rx_sensitivity_dbm (the base
    receiver) and losses_db.  ``portable`` carries tx_power_dbm, ant_gain_dbi,
    rx_sensitivity_dbm, h_ut_m plus body_loss_db / penetration_class.
    """
    _, _, dist_m = _GEOD.inv(lon1, lat1, lon2, lat2)
    if samples is None:
        samples = int(np.clip(dist_m / 75.0, 32, 512))
    prof = fusion.profile(lat1, lon1, lat2, lon2, n_samples=samples,
                          grid=grid, georef=georef)
    d, elev = prof.distances_m, prof.elevations_m
    freq = float(base["freq_mhz"])
    h_bs = float(base["h_bs_m"])
    h_ut = float(portable["h_ut_m"])

    rf = analyze_path(d, elev, h_bs, h_ut, freq, k=k)
    pl, warnings = path_loss_db(base["model"], np.maximum(d[-1:], 1.0), freq,
                               h_bs, h_ut, base.get("environment", "urban"))
    curved = apply_earth_curvature(d, elev, k=k)
    diff = deygout_loss_db(d, curved, h_bs, h_ut, freq)

    env = foliage_loss_db(freq, foliage_depth_m)
    env += gaseous_attenuation_db_per_km(freq) * dist_m / 1000.0
    env += rain_loss_db(freq, dist_m, rain_rate_mm_h)
    if clutter_pct > 0:
        env += float(clutter_loss_db(freq, dist_m, clutter_pct))

    g_base = float(base.get("ant_gain_dbi", base.get("tx_gain_dbi", 0.0)))
    g_port = float(portable.get("ant_gain_dbi", portable.get("rx_gain_dbi", 0.0)))
    losses = float(base.get("losses_db", 0.0))
    extra = _penetration_db(portable)
    common = float(pl[-1]) + diff + env + extra   # reciprocal path terms

    rx_out = float(base["tx_power_dbm"]) + g_base + g_port - losses - common
    rx_in = float(portable["tx_power_dbm"]) + g_port + g_base - losses - common

    verdict = _talkback_verdict(
        rx_out, rx_in, float(portable["rx_sensitivity_dbm"]),
        float(base["rx_sensitivity_dbm"]), target_daq, faded_margin_db)
    return {
        "distance_m": round(float(dist_m), 1),
        "los_clear": rf["line_of_sight_clear"],
        "path_loss_db": round(float(pl[-1]), 1),
        "diffraction_loss_db": round(diff, 1),
        "environment_loss_db": round(env, 1),
        "portable_excess_db": round(extra, 1),
        "warnings": warnings,
        **verdict,
    }


def twoway_coverage(engine, base: dict, portable: dict,
                    lat: float, lon: float, radius_m: float = 8000.0,
                    target_daq: float = 3.4,
                    faded_margin_db: float = DEFAULT_FADED_MARGIN_DB,
                    antenna_azimuth_deg: float | None = None,
                    antenna_beamwidth_deg: float = 65.0,
                    downtilt_deg: float = 0.0,
                    shadow_margin_db: float = 0.0,
                    foliage_depth_m: float = 0.0, rain_rate_mm_h: float = 0.0,
                    clutter_pct: float = 0.0, k: float = K_FACTOR_DEFAULT,
                    grid=None, georef=None,
                    n_radials: int = 120, n_steps: int = 80) -> dict:
    """Area talk-back study: talk-out, talk-in and reliable (both) fractions.

    Runs ONE downlink polar sweep (base -> portable) via the coverage engine,
    then derives the uplink field by reciprocity and classifies every polar
    cell's limiting direction.  ``reliable`` = both directions meet target DAQ.
    """
    g_base = float(base.get("ant_gain_dbi", base.get("tx_gain_dbi", 0.0)))
    g_port = float(portable.get("ant_gain_dbi", portable.get("rx_gain_dbi", 0.0)))
    losses = float(base.get("losses_db", 0.0))
    port_sens = float(portable["rx_sensitivity_dbm"])
    base_sens = float(base["rx_sensitivity_dbm"])
    extra = _penetration_db(portable)

    # Map the two-way parties onto a downlink "tech" dict for compute_polar.
    tech = {
        "freq_mhz": float(base["freq_mhz"]), "model": base["model"],
        "environment": base.get("environment", "urban"),
        "tx_power_dbm": float(base["tx_power_dbm"]),
        "tx_gain_dbi": g_base, "rx_gain_dbi": g_port, "losses_db": losses,
        "rx_sensitivity_dbm": port_sens,
        "h_bs_m": float(base["h_bs_m"]), "h_ut_m": float(portable["h_ut_m"]),
    }
    polar = engine.compute_polar(
        lat, lon, tech, radius_m=radius_m, n_radials=n_radials, n_steps=n_steps,
        antenna_azimuth_deg=antenna_azimuth_deg,
        antenna_beamwidth_deg=antenna_beamwidth_deg, downtilt_deg=downtilt_deg,
        shadow_margin_db=shadow_margin_db, foliage_depth_m=foliage_depth_m,
        rain_rate_mm_h=rain_rate_mm_h, clutter_pct=clutter_pct, k=k,
        grid=grid, georef=georef)

    rx_out = polar["rx_power"] - extra                     # base -> portable
    swap = float(portable["tx_power_dbm"]) - float(base["tx_power_dbm"])
    rx_in = rx_out + swap                                  # portable -> base

    anchor_out = port_sens + faded_margin_db
    anchor_in = base_sens + faded_margin_db
    ok_out = rx_out >= anchor_out
    ok_in = rx_in >= anchor_in
    reliable = ok_out & ok_in

    # Area weights: annulus area grows with range, so weight by distance.
    w = polar["dist_g"] / polar["dist_g"].sum()
    frac = lambda m: round(float(np.sum(m * w)), 4)
    # Of the reliable area, which direction is the tighter constraint?
    margin_out = rx_out - anchor_out
    margin_in = rx_in - anchor_in
    limited_by_in = frac((margin_in < margin_out) & reliable)
    return {
        "tx_elevation_m": round(polar["tx_elev"], 1),
        "talk_out_area_fraction": frac(ok_out),
        "talk_in_area_fraction": frac(ok_in),
        "reliable_talkback_fraction": frac(reliable),
        "reliable_limited_by_talk_in": limited_by_in,
        "reliable_limited_by_talk_out": round(
            frac(reliable) - limited_by_in, 4),
        "target_daq": target_daq,
        "swap_db": round(swap, 1),
        "portable_excess_db": round(extra, 1),
        "warnings": polar["warnings"],
    }


def repeater_cascade(corridor_km: float, reliable_range_km: float,
                     overlap_pct: float = 15.0) -> dict:
    """Number and spacing of cascaded repeaters for continuous talk-back along
    a corridor (highway / rail / haul road / tunnel run).

    Each repeater delivers reliable talk-back to ``reliable_range_km`` either
    side; neighbours overlap by ``overlap_pct`` for hand-off, so the effective
    spacing is ``2 * range * (1 - overlap)``.
    """
    if reliable_range_km <= 0:
        raise ValueError("reliable_range_km must be positive")
    overlap = max(0.0, min(overlap_pct, 90.0)) / 100.0
    spacing = 2.0 * reliable_range_km * (1.0 - overlap)
    count = max(1, int(np.ceil(corridor_km / spacing)))
    # Even spacing with half-spacing offset so the ends are covered.
    positions = [round((i + 0.5) * corridor_km / count, 2) for i in range(count)]
    return {
        "repeaters": count,
        "spacing_km": round(spacing, 2),
        "positions_km": positions,
        "overlap_pct": overlap_pct,
        "reliable_range_km": reliable_range_km,
    }
