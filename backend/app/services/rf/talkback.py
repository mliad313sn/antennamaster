"""Bidirectional "talk-back" LMR engine: two-way link balance, DAQ grading
and repeater-system design.

Classic coverage prediction is *downlink only* — infrastructure (base or
repeater) transmitting to a receiver.  Land-mobile-radio (LMR) systems for
public safety, mining, rail and utilities live or die on **two-way** service:
a portable radio held at head height, running 1-5 W into a body-worn antenna,
must both *hear* the base (talk-out / downlink) **and** *be heard* by it
(talk-in / uplink).  Coverage is bounded by the weaker of the two directions.

This module adds three things the downlink engine cannot express:

* **Portable-radio profiles** — body loss, 1.5 m antenna height, in-building /
  in-vehicle penetration and per-device EIRP, so the user endpoint is modelled
  as the lossy, low-power, obstructed device it really is.
* **Bidirectional link balance** — path loss is reciprocal, so it is computed
  once over the fused terrain profile and applied to *two* budgets (base->
  portable and portable->base) whose asymmetric powers/gains/sensitivities
  usually differ by 10+ dB.
* **DAQ grading (TIA-4046 / TSB-88)** — the delivered-audio-quality grade that
  LMR tenders are actually written in, derived from each direction's fade
  margin and intersected (combined DAQ = min(talk-out, talk-in)).

Plus a **repeater-system** helper: donor/coverage antenna isolation, the
feedback-stable maximum gain, and cascade spacing for continuous talk-back
along a route.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ...config import K_FACTOR_DEFAULT
from .environment import (clutter_loss_db, foliage_loss_db,
                          gaseous_attenuation_db_per_km, rain_loss_db)
from .models import deygout_loss_db, path_loss_db
from .physics import analyze_path, apply_earth_curvature

C_LIGHT = 299_792_458.0


# --------------------------------------------------------------------------- #
#  Delivered Audio Quality (TIA-4046 / TSB-88)
# --------------------------------------------------------------------------- #
# TSB-88 designs to a Channel Performance Criterion (CPC) expressed as a DAQ
# level.  In predictive planning the receiver's static reference sensitivity is
# taken as the Faded Performance Threshold for the design CPC (DAQ 3.4, the
# public-safety minimum); higher DAQ grades require progressively more signal
# above that threshold.  The margin->DAQ ladder below is that translation and
# is override-able so an operator can align it to a measured CPC table.
DAQ_LADDER: list[tuple[float, float, str]] = [
    # (min margin dB above reference sensitivity, DAQ value, description)
    (22.0, 5.0, "Speech easily understood"),
    (15.0, 4.5, "Speech easily understood, rare repetition"),
    (10.0, 4.0, "Speech easily understood, occasional repetition"),
    (5.0, 3.4, "Speech understandable with effort — public-safety minimum"),
    (0.0, 3.0, "Speech understandable with slight effort / repetition"),
    (-5.0, 2.0, "Understandable only with considerable effort"),
    (-100.0, 1.0, "Unusable — speech present but not understandable"),
]


def daq_from_margin(margin_db: float,
                    ladder: list[tuple[float, float, str]] | None = None) -> dict:
    """Map a fade margin (dB above reference sensitivity) to a DAQ grade."""
    for min_margin, daq, desc in (ladder or DAQ_LADDER):
        if margin_db >= min_margin:
            return {"daq": daq, "description": desc, "margin_db": round(margin_db, 1)}
    last = (ladder or DAQ_LADDER)[-1]
    return {"daq": last[1], "description": last[2], "margin_db": round(margin_db, 1)}


# --------------------------------------------------------------------------- #
#  Portable / mobile radio profiles
# --------------------------------------------------------------------------- #
# EIRP-affecting device parameters.  ``tx_power_dbm`` is the conducted PA power
# (30 dBm = 1 W, 37 dBm = 5 W); ``antenna_gain_dbi`` is typically 0 to -3 dBi
# for a stubby whip against a handheld.  ``body_loss_db`` is the shadowing of
# the user's body for a body-worn radio; ``building_penetration_db`` /
# ``vehicle_penetration_db`` are added when the user is served indoors / mobile.
PORTABLE_PROFILES: dict[str, dict] = {
    "portable_handheld_5w": {
        "label": "Handheld portable, 5 W (belt/hand, on-street)",
        "tx_power_dbm": 37.0, "antenna_gain_dbi": -2.0, "antenna_height_m": 1.5,
        "body_loss_db": 3.0, "building_penetration_db": 0.0,
        "vehicle_penetration_db": 0.0, "rx_sensitivity_dbm": -119.0,
        "rx_gain_dbi": -2.0,
    },
    "portable_bodyworn_5w": {
        "label": "Body-worn portable, 5 W (on-hip, heavy body shadowing)",
        "tx_power_dbm": 37.0, "antenna_gain_dbi": -3.0, "antenna_height_m": 1.2,
        "body_loss_db": 6.0, "building_penetration_db": 0.0,
        "vehicle_penetration_db": 0.0, "rx_sensitivity_dbm": -119.0,
        "rx_gain_dbi": -3.0,
    },
    "portable_indoor_5w": {
        "label": "Handheld portable, 5 W, in-building",
        "tx_power_dbm": 37.0, "antenna_gain_dbi": -2.0, "antenna_height_m": 1.5,
        "body_loss_db": 4.0, "building_penetration_db": 15.0,
        "vehicle_penetration_db": 0.0, "rx_sensitivity_dbm": -119.0,
        "rx_gain_dbi": -2.0,
    },
    "mobile_vehicular_25w": {
        "label": "Mobile radio, 25 W, roof-mount (in-vehicle user)",
        "tx_power_dbm": 44.0, "antenna_gain_dbi": 2.5, "antenna_height_m": 1.6,
        "body_loss_db": 0.0, "building_penetration_db": 0.0,
        "vehicle_penetration_db": 8.0, "rx_sensitivity_dbm": -119.0,
        "rx_gain_dbi": 2.5,
    },
    "portable_uhf_1w": {
        "label": "Low-power handheld, 1 W (licence-free / short range)",
        "tx_power_dbm": 30.0, "antenna_gain_dbi": -3.0, "antenna_height_m": 1.5,
        "body_loss_db": 4.0, "building_penetration_db": 0.0,
        "vehicle_penetration_db": 0.0, "rx_sensitivity_dbm": -116.0,
        "rx_gain_dbi": -3.0,
    },
}


def get_portable_profile(key: str, overrides: dict | None = None) -> dict:
    if key not in PORTABLE_PROFILES:
        raise ValueError(f"Unknown portable profile: {key!r}")
    prof = dict(PORTABLE_PROFILES[key])
    if overrides:
        prof.update({k: v for k, v in overrides.items() if v is not None})
    return prof


def _portable_penetration_db(portable: dict, environment: str) -> float:
    """Extra loss for where the *portable* is used (on-street/indoor/vehicle)."""
    loss = float(portable.get("body_loss_db", 0.0))
    if environment == "in_building":
        loss += float(portable.get("building_penetration_db", 0.0))
    elif environment == "in_vehicle":
        loss += float(portable.get("vehicle_penetration_db", 0.0))
    return loss


# --------------------------------------------------------------------------- #
#  Bidirectional link balance over a fused terrain path
# --------------------------------------------------------------------------- #
@dataclass
class TalkBackResult:
    distance_m: float
    path_loss_db: float
    diffraction_loss_db: float
    environment_loss_db: float
    talk_out: dict          # base -> portable (downlink)
    talk_in: dict           # portable -> base (uplink)
    combined: dict          # min-of-two DAQ and served
    limiting_direction: str
    los_clear: bool
    warnings: list[str]


def bidirectional_link(fusion, tech: dict, portable: dict,
                       lat1: float, lon1: float, lat2: float, lon2: float,
                       user_environment: str = "on_street",
                       k: float = K_FACTOR_DEFAULT,
                       foliage_depth_m: float = 0.0,
                       rain_rate_mm_h: float = 0.0,
                       clutter_pct: float = 0.0,
                       daq_ladder: list | None = None,
                       samples: int | None = None,
                       grid=None, georef=None) -> TalkBackResult:
    """Two-way link balance between a base/repeater (``tech``) at (lat1,lon1)
    and a portable radio (``portable``) at (lat2,lon2).

    Path loss, diffraction and environmental loss are **reciprocal** — computed
    once over the fused profile — and applied to two asymmetric budgets:

    * **talk-out** (downlink): base EIRP -> portable RX (+ body/penetration).
    * **talk-in**  (uplink):   portable EIRP -> base RX (+ body/penetration).

    Combined service is the intersection: DAQ = min(out, in), served = both.
    """
    from pyproj import Geod
    geod = Geod(ellps="WGS84")
    _, _, dist_m = geod.inv(lon1, lat1, lon2, lat2)
    if samples is None:
        samples = int(np.clip(dist_m / 75.0, 32, 512))

    prof = fusion.profile(lat1, lon1, lat2, lon2, n_samples=samples,
                          grid=grid, georef=georef)
    d, elev = prof.distances_m, prof.elevations_m
    freq = float(tech["freq_mhz"])
    h_base = float(tech["h_bs_m"])
    h_port = float(portable.get("antenna_height_m", 1.5))

    # Geometry / LOS (base as tx-height, portable as rx-height — reciprocal).
    rf = analyze_path(d, elev, h_base, h_port, freq, k=k)

    # Reciprocal path loss + diffraction (same both directions).
    pl, warnings = path_loss_db(tech["model"], np.maximum(d[-1:], 1.0), freq,
                                h_base, h_port, tech.get("environment", "urban"))
    pl_db = float(pl[-1])
    curved = apply_earth_curvature(d, elev, k=k)
    diff = float(deygout_loss_db(d, curved, h_base, h_port, freq))

    env = foliage_loss_db(freq, foliage_depth_m)
    env += gaseous_attenuation_db_per_km(freq) * dist_m / 1000.0
    env += rain_loss_db(freq, dist_m, rain_rate_mm_h)
    if clutter_pct > 0:
        env += float(clutter_loss_db(freq, dist_m, clutter_pct))

    penetration = _portable_penetration_db(portable, user_environment)
    common_loss = pl_db + diff + env + penetration

    # --- talk-out: base transmits, portable receives -----------------------
    base_eirp = float(tech["tx_power_dbm"]) + float(tech["tx_gain_dbi"]) \
        - float(tech.get("losses_db", 0.0))
    out_rx = base_eirp + float(portable.get("rx_gain_dbi", 0.0)) - common_loss
    out_margin = out_rx - float(portable["rx_sensitivity_dbm"])
    out = {"rx_power_dbm": round(out_rx, 1),
           "sensitivity_dbm": float(portable["rx_sensitivity_dbm"]),
           "margin_db": round(out_margin, 1),
           "served": bool(out_margin >= 0.0),
           **daq_from_margin(out_margin, daq_ladder)}

    # --- talk-in: portable transmits, base receives ------------------------
    port_eirp = float(portable["tx_power_dbm"]) + float(portable.get("antenna_gain_dbi", 0.0))
    in_rx = port_eirp + float(tech["rx_gain_dbi"]) - float(tech.get("losses_db", 0.0)) \
        - common_loss
    base_sens = float(tech["rx_sensitivity_dbm"])
    in_margin = in_rx - base_sens
    tin = {"rx_power_dbm": round(in_rx, 1),
           "sensitivity_dbm": base_sens,
           "margin_db": round(in_margin, 1),
           "served": bool(in_margin >= 0.0),
           **daq_from_margin(in_margin, daq_ladder)}

    combined_daq = min(out["daq"], tin["daq"])
    limiting = "talk_in" if in_margin <= out_margin else "talk_out"
    combined = {"daq": combined_daq,
                "served": bool(out["served"] and tin["served"]),
                "limiting_margin_db": round(min(out_margin, in_margin), 1)}

    return TalkBackResult(
        distance_m=round(float(dist_m), 1),
        path_loss_db=round(pl_db, 1),
        diffraction_loss_db=round(diff, 1),
        environment_loss_db=round(env + penetration, 1),
        talk_out=out, talk_in=tin, combined=combined,
        limiting_direction=limiting,
        los_clear=rf["line_of_sight_clear"],
        warnings=list(warnings),
    )


# --------------------------------------------------------------------------- #
#  Repeater-system design
# --------------------------------------------------------------------------- #
def antenna_isolation_db(freq_mhz: float, separation_m: float,
                         arrangement: str = "vertical",
                         tx_gain_dbi: float = 0.0, rx_gain_dbi: float = 0.0,
                         horizontal_pattern_loss_db: float = 0.0) -> float:
    """Free-space isolation between a repeater's donor and coverage antennas.

    Vertical (stacked) separation gives the most isolation for the least space:
        Iso_v = 28 + 40*log10(d/lambda)              [dB]
    Horizontal separation:
        Iso_h = 22 + 20*log10(d/lambda) - Gt - Gr + FBR-ish pattern discount
    (standard Bird/Anritsu co-site formulas).  Isolation must exceed the
    repeater gain by a stability margin or the loop oscillates.
    """
    lam = C_LIGHT / (freq_mhz * 1e6)
    d = max(separation_m, lam / 10.0)
    if arrangement == "vertical":
        return 28.0 + 40.0 * np.log10(d / lam)
    # horizontal
    iso = 22.0 + 20.0 * np.log10(d / lam)
    iso += horizontal_pattern_loss_db - tx_gain_dbi - rx_gain_dbi
    return float(iso)


def repeater_stability(system_gain_db: float, isolation_db: float,
                       stability_margin_db: float = 15.0) -> dict:
    """A bidirectional amplifier / repeater is stable only if the antenna
    isolation exceeds the through gain by the stability margin (typ. 12-15 dB).
    Returns the max stable gain and whether the requested gain is safe."""
    max_stable = isolation_db - stability_margin_db
    return {
        "isolation_db": round(float(isolation_db), 1),
        "system_gain_db": round(float(system_gain_db), 1),
        "stability_margin_db": stability_margin_db,
        "max_stable_gain_db": round(float(max_stable), 1),
        "stable": bool(system_gain_db <= max_stable),
        "headroom_db": round(float(max_stable - system_gain_db), 1),
    }


def cascade_spacing(reliable_range_m: float, overlap_fraction: float = 0.15) -> dict:
    """Spacing of repeaters along a linear route (highway/rail/tunnel access)
    for continuous talk-back.  Each repeater serves ``reliable_range_m`` on
    each side; consecutive cells overlap by ``overlap_fraction`` for handoff.

        spacing = 2 * R * (1 - overlap)
    """
    r = max(reliable_range_m, 1.0)
    spacing = 2.0 * r * (1.0 - float(np.clip(overlap_fraction, 0.0, 0.5)))
    return {
        "reliable_range_m": round(r, 1),
        "overlap_fraction": overlap_fraction,
        "spacing_m": round(spacing, 1),
        "repeaters_per_km": round(1000.0 / spacing, 3) if spacing > 0 else None,
    }


def repeater_design(freq_mhz: float, system_gain_db: float,
                    donor_coverage_separation_m: float,
                    arrangement: str = "vertical",
                    stability_margin_db: float = 15.0,
                    reliable_range_m: float | None = None,
                    overlap_fraction: float = 0.15,
                    tx_gain_dbi: float = 0.0, rx_gain_dbi: float = 0.0) -> dict:
    """Full repeater-system verdict: donor isolation, feedback stability and
    (optionally) cascade spacing for a linear deployment."""
    iso = antenna_isolation_db(freq_mhz, donor_coverage_separation_m,
                               arrangement, tx_gain_dbi, rx_gain_dbi)
    result = {
        "frequency_mhz": freq_mhz,
        "arrangement": arrangement,
        "donor_coverage_separation_m": donor_coverage_separation_m,
        "isolation": repeater_stability(system_gain_db, iso, stability_margin_db),
    }
    if reliable_range_m is not None:
        result["cascade"] = cascade_spacing(reliable_range_m, overlap_fraction)
    return result
