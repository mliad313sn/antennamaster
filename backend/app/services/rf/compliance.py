"""RF-exposure / EMF compliance: ICNIRP and FCC OET-65 MPE assessment.

No compliance module, no permit.  Before an antenna is switched on, the
installer must show the public and workers are not over-exposed.  This module
computes the far-field power density around an antenna and the *compliance
distances* -- how far the public and occupational exclusion zones extend --
against the two reference standards used worldwide:

  * ICNIRP (International Commission on Non-Ionizing Radiation Protection) --
    the basis for EU and much of the world's limits;
  * FCC OET-65 -- the US Maximum Permissible Exposure limits.

Far-field power density of an antenna of EIRP ``P`` at distance ``r``::

    S = P / (4*pi*r^2)     [W/m^2]

(a ground-reflection factor of up to x2.56 in field, i.e. x1.6 in power, is
offered for a worst-case reflective environment per FCC OET-65).  The
compliance distance inverts this for the limit S_lim::

    r_lim = sqrt(P * reflect / (4*pi*S_lim))

Both standards' limits are frequency-dependent and split into general-public
(uncontrolled) and occupational (controlled) tiers.
"""
from __future__ import annotations

import numpy as np


def icnirp_limit_w_m2(freq_mhz: float, occupational: bool = False) -> float:
    """ICNIRP reference power-density limit (W/m^2) for the frequency."""
    f = freq_mhz
    if f < 10.0:
        # Below 10 MHz power-density limits are not the controlling metric;
        # return the 10 MHz value as a conservative proxy.
        f = 10.0
    if occupational:
        if f <= 400.0:
            return 10.0
        if f <= 2000.0:
            return f / 40.0
        return 50.0
    # General public.
    if f <= 400.0:
        return 2.0
    if f <= 2000.0:
        return f / 200.0
    return 10.0


def fcc_mpe_w_m2(freq_mhz: float, occupational: bool = False) -> float:
    """FCC OET-65 MPE limit converted to W/m^2 (1 mW/cm^2 = 10 W/m^2)."""
    f = freq_mhz
    if occupational:  # controlled
        if f < 1.34:
            return 1000.0
        if f < 30.0:
            return (1800.0 / f ** 2) * 10.0
        if f < 300.0:
            return 10.0                     # 1.0 mW/cm^2
        if f < 1500.0:
            return (f / 300.0) * 10.0
        return 50.0                         # 5.0 mW/cm^2
    # Uncontrolled / general population.
    if f < 1.34:
        return 1000.0
    if f < 30.0:
        return (180.0 / f ** 2) * 10.0
    if f < 300.0:
        return 2.0                          # 0.2 mW/cm^2
    if f < 1500.0:
        return (f / 1500.0) * 10.0
    return 10.0                             # 1.0 mW/cm^2


def power_density_w_m2(eirp_dbm: float, distance_m: float,
                       reflection_factor: float = 1.0) -> float:
    """Far-field power density (W/m^2) at ``distance_m`` from an EIRP source."""
    eirp_w = 10.0 ** ((eirp_dbm - 30.0) / 10.0)
    r = max(distance_m, 0.01)
    return eirp_w * reflection_factor / (4.0 * np.pi * r * r)


def compliance_distance_m(eirp_dbm: float, limit_w_m2: float,
                          reflection_factor: float = 1.0) -> float:
    """Distance at which the power density falls to ``limit_w_m2``."""
    eirp_w = 10.0 ** ((eirp_dbm - 30.0) / 10.0)
    if limit_w_m2 <= 0:
        return float("inf")
    return float(np.sqrt(eirp_w * reflection_factor / (4.0 * np.pi * limit_w_m2)))


def assess_exposure(freq_mhz: float, tx_power_dbm: float,
                    antenna_gain_dbi: float, losses_db: float = 0.0,
                    ground_reflection: bool = False,
                    standard: str = "icnirp",
                    assess_distance_m: float | None = None) -> dict:
    """Full EMF compliance assessment for one antenna.

    Returns the EIRP, the public and occupational limits, the compliance
    (exclusion-zone) distances, and -- if ``assess_distance_m`` is given --
    whether that distance is compliant and its exposure ratio (%% of limit).
    """
    eirp_dbm = tx_power_dbm + antenna_gain_dbi - losses_db
    reflect = 1.6 if ground_reflection else 1.0     # OET-65 worst-case power x1.6
    limit_fn = fcc_mpe_w_m2 if standard.lower() == "fcc" else icnirp_limit_w_m2
    pub = limit_fn(freq_mhz, occupational=False)
    occ = limit_fn(freq_mhz, occupational=True)

    out = {
        "standard": standard.lower(),
        "eirp_dbm": round(eirp_dbm, 1),
        "eirp_w": round(10.0 ** ((eirp_dbm - 30.0) / 10.0), 2),
        "ground_reflection": ground_reflection,
        "public_limit_w_m2": round(pub, 4),
        "occupational_limit_w_m2": round(occ, 4),
        "public_compliance_distance_m": round(
            compliance_distance_m(eirp_dbm, pub, reflect), 2),
        "occupational_compliance_distance_m": round(
            compliance_distance_m(eirp_dbm, occ, reflect), 2),
    }
    if assess_distance_m is not None:
        s = power_density_w_m2(eirp_dbm, assess_distance_m, reflect)
        out["assess_distance_m"] = assess_distance_m
        out["power_density_w_m2"] = round(s, 4)
        out["public_exposure_pct"] = round(100.0 * s / pub, 1) if pub else None
        out["occupational_exposure_pct"] = round(100.0 * s / occ, 1) if occ else None
        out["public_compliant"] = bool(s <= pub)
        out["occupational_compliant"] = bool(s <= occ)
    return out
