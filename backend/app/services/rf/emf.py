"""RF-exposure (EMF) compliance: FCC OET-65 and ICNIRP maximum permissible
exposure (MPE), and the resulting exclusion-zone distances around a TX.

Radio-site permitting requires proving the public cannot be exposed above the
regulatory power-density limit.  In the far field the boresight power density is

    S(r) = EIRP * F / (4*pi*r^2)          [W/m^2]

with ``F`` a ground-reflection field enhancement (FCC uses 2.56 = 1.6^2 for a
worst-case in-phase ground reflection).  The compliance distance is the r at
which S equals the MPE limit:

    r = sqrt(EIRP * F / (4*pi*S_limit))

Two limits apply: **occupational/controlled** (trained workers) and
**public/uncontrolled** (general public), the latter 5x stricter.  From a
mounting height h, the horizontal ground-level extent of the zone is
sqrt(r^2 - h^2).
"""
from __future__ import annotations

import numpy as np

# --------------------------------------------------------------------------- #
#  MPE limits (power density, W/m^2) as a function of frequency (MHz)
# --------------------------------------------------------------------------- #
def fcc_mpe_wm2(freq_mhz: float, public: bool) -> float:
    """FCC OET-65 Table 1 MPE power density (converted mW/cm^2 -> W/m^2)."""
    f = float(freq_mhz)
    if public:
        if f < 1.34:
            s = 100.0
        elif f < 30.0:
            s = 180.0 / f ** 2
        elif f < 300.0:
            s = 0.2
        elif f < 1500.0:
            s = f / 1500.0
        else:
            s = 1.0
    else:  # occupational / controlled
        if f < 3.0:
            s = 100.0
        elif f < 30.0:
            s = 900.0 / f ** 2
        elif f < 300.0:
            s = 1.0
        elif f < 1500.0:
            s = f / 300.0
        else:
            s = 5.0
    return s * 10.0            # mW/cm^2 -> W/m^2


def icnirp_mpe_wm2(freq_mhz: float, public: bool) -> float:
    """ICNIRP reference-level power density (W/m^2), general public vs
    occupational (1998 basis, 10 MHz-300 GHz range)."""
    f = float(freq_mhz)
    if public:
        if f < 400.0:
            return 2.0
        if f < 2000.0:
            return f / 200.0
        return 10.0
    if f < 400.0:
        return 10.0
    if f < 2000.0:
        return f / 40.0
    return 50.0


LIMIT_STANDARDS = {"fcc": fcc_mpe_wm2, "icnirp": icnirp_mpe_wm2}


def eirp_watts(tx_power_dbm: float, gain_dbi: float, losses_db: float = 0.0) -> float:
    """EIRP in watts from dBm power + dBi gain - feed losses."""
    eirp_dbm = tx_power_dbm + gain_dbi - losses_db
    return 10.0 ** (eirp_dbm / 10.0) / 1000.0


def compliance_distance_m(eirp_w: float, limit_wm2: float,
                          reflection_factor: float = 2.56) -> float:
    """Boresight distance at which power density falls to the MPE limit."""
    if limit_wm2 <= 0:
        return float("inf")
    return float(np.sqrt(eirp_w * reflection_factor / (4.0 * np.pi * limit_wm2)))


def exposure_zones(freq_mhz: float, tx_power_dbm: float, gain_dbi: float,
                   losses_db: float = 0.0, mount_height_m: float = 15.0,
                   standard: str = "fcc",
                   reflection_factor: float = 2.56) -> dict:
    """Full EMF-compliance verdict for one antenna: MPE limits, boresight
    power density at 1 m, and occupational/public exclusion-zone distances
    (slant radius + horizontal ground-level extent from the mount height)."""
    limit_fn = LIMIT_STANDARDS.get(standard, fcc_mpe_wm2)
    eirp = eirp_watts(tx_power_dbm, gain_dbi, losses_db)
    s_occ = limit_fn(freq_mhz, public=False)
    s_pub = limit_fn(freq_mhz, public=True)
    r_occ = compliance_distance_m(eirp, s_occ, reflection_factor)
    r_pub = compliance_distance_m(eirp, s_pub, reflection_factor)

    def ground(r: float) -> float:
        return float(np.sqrt(max(r ** 2 - mount_height_m ** 2, 0.0)))

    s_at_1m = eirp * reflection_factor / (4.0 * np.pi * 1.0)
    return {
        "standard": standard,
        "freq_mhz": freq_mhz,
        "eirp_w": round(eirp, 3),
        "eirp_dbm": round(tx_power_dbm + gain_dbi - losses_db, 1),
        "reflection_factor": reflection_factor,
        "mpe_occupational_wm2": round(s_occ, 4),
        "mpe_public_wm2": round(s_pub, 4),
        "power_density_at_1m_wm2": round(s_at_1m, 4),
        "occupational": {
            "mpe_wm2": round(s_occ, 4),
            "compliance_distance_m": round(r_occ, 2),
            "ground_extent_m": round(ground(r_occ), 2),
            "compliant_at_ground": bool(mount_height_m >= r_occ)},
        "public": {
            "mpe_wm2": round(s_pub, 4),
            "compliance_distance_m": round(r_pub, 2),
            "ground_extent_m": round(ground(r_pub), 2),
            "compliant_at_ground": bool(mount_height_m >= r_pub)},
    }
