"""Annual availability of a microwave link — ITU-R P.530 method.

Turns a fade margin into the number operators actually contract on: the
percentage of the year the hop is up ("four nines", "five nines").

Two outage mechanisms, combined:

MULTIPATH (clear-air) — the P.530 quick-planning fade-occurrence method:

    p0 [%] = K · d^3.4 · (1+|εp|)^−1.03 · f^0.8 · 10^(−0.00076·hc)
    K      = 10^(−4.6 − 0.0027·dN1)          (geoclimatic factor)
    p_mp   = p0 · 10^(−M/10)                 (deep-fade probability at margin M)

with d in km, f in GHz, εp the path inclination in mrad, hc the lower antenna
altitude (m a.s.l.) and dN1 the point refractivity gradient not exceeded 1 %
of the time (region-dependent; −400 ≈ very variable coastal, −100 ≈ stable).

RAIN — specific attenuation from the existing ITU-R P.838 coefficients at the
zone's R0.01 rate (classic P.837 rain-zone table A…Q), effective path length
d_eff = d/(1+d/d0) with d0 = 35·e^(−0.015·R0.01), then the P.530 scaling
Ap/A0.01 = 0.12·p^−(0.546+0.043·log10 p) inverted by bisection to find the
time percentage p at which rain fade equals the margin.

The formulas are the published P.530 planning method; results are labelled
with the method so a designer knows exactly what standard produced them.
"""
from __future__ import annotations

import math

# Classic ITU-R P.837 rain-climate zones: rain rate exceeded 0.01% of the year.
RAIN_ZONES_R001 = {
    "A": 8.0, "B": 12.0, "C": 15.0, "D": 19.0, "E": 22.0, "F": 28.0,
    "G": 30.0, "H": 32.0, "J": 35.0, "K": 42.0, "L": 60.0, "M": 63.0,
    "N": 95.0, "P": 145.0, "Q": 115.0,
}


def geoclimatic_factor(dn1: float = -300.0) -> float:
    """K = 10^(−4.6 − 0.0027·dN1) — P.530 quick-planning geoclimatic factor."""
    return 10.0 ** (-4.6 - 0.0027 * dn1)


def multipath_outage_pct(d_km: float, f_ghz: float, h_tx_masl: float,
                         h_rx_masl: float, fade_margin_db: float,
                         dn1: float = -300.0) -> float:
    """% of the year the clear-air fade exceeds the margin (P.530 quick method)."""
    if d_km <= 0 or f_ghz <= 0:
        raise ValueError("distance and frequency must be positive")
    k = geoclimatic_factor(dn1)
    eps_p = abs(h_tx_masl - h_rx_masl) / d_km / 1000.0 * 1000.0  # mrad
    hc = min(h_tx_masl, h_rx_masl)
    p0 = (k * d_km ** 3.4 * (1.0 + abs(eps_p)) ** -1.03 * f_ghz ** 0.8
          * 10.0 ** (-0.00076 * hc))
    return float(min(p0 * 10.0 ** (-fade_margin_db / 10.0), 100.0))


def rain_attenuation_001(d_km: float, f_ghz: float, zone: str,
                         polarization: str = "h") -> float:
    """Rain attenuation exceeded 0.01% of the year (dB): γR(R0.01)·d_eff."""
    from .environment import rain_specific_attenuation
    r001 = RAIN_ZONES_R001.get(zone.upper())
    if r001 is None:
        raise ValueError(f"Unknown rain zone {zone!r} (A..Q)")
    gamma = rain_specific_attenuation(f_ghz * 1000.0, r001)
    d0 = 35.0 * math.exp(-0.015 * min(r001, 100.0))
    d_eff = d_km / (1.0 + d_km / d0)
    return float(gamma * d_eff)


def _ap_over_a001(p_pct: float) -> float:
    """P.530 rain-fade depth scaling Ap/A0.01 (latitudes ≥ 30°)."""
    return 0.12 * p_pct ** -(0.546 + 0.043 * math.log10(p_pct))


def rain_outage_pct(d_km: float, f_ghz: float, zone: str,
                    fade_margin_db: float) -> float:
    """% of the year rain fade exceeds the margin (bisection on the P.530
    Ap/A0.01 scaling). 0 when even 1% rain fade never reaches the margin."""
    a001 = rain_attenuation_001(d_km, f_ghz, zone)
    if a001 <= 0:
        return 0.0
    def fade_at(p):     # dB fade exceeded p% of the year
        return a001 * _ap_over_a001(p)
    if fade_at(1.0) >= fade_margin_db:
        return 1.0                                     # ≥1% outage: dire link
    if fade_at(1e-5) < fade_margin_db:
        return 0.0                                     # margin never exceeded
    lo, hi = 1e-5, 1.0                                 # fade_at decreasing in p
    for _ in range(60):
        mid = math.sqrt(lo * hi)                       # log-space bisection
        if fade_at(mid) >= fade_margin_db:
            lo = mid
        else:
            hi = mid
    return float(lo)


def _nines_label(avail_pct: float) -> str:
    if avail_pct >= 99.999:
        return "five nines (99.999%)"
    if avail_pct >= 99.99:
        return "four nines (99.99%)"
    if avail_pct >= 99.9:
        return "three nines (99.9%)"
    if avail_pct >= 99.0:
        return "two nines (99%)"
    return "below 99%"


def link_availability(d_km: float, f_ghz: float, h_tx_masl: float,
                      h_rx_masl: float, fade_margin_db: float,
                      rain_zone: str = "K", dn1: float = -300.0) -> dict:
    """Annual availability breakdown for one hop (P.530 planning method)."""
    p_mp = multipath_outage_pct(d_km, f_ghz, h_tx_masl, h_rx_masl,
                                fade_margin_db, dn1)
    p_rain = rain_outage_pct(d_km, f_ghz, rain_zone, fade_margin_db)
    outage = min(p_mp + p_rain, 100.0)
    avail = 100.0 - outage
    return {
        "method": "ITU-R P.530 quick planning (multipath) + P.837/P.838 rain",
        "fade_margin_db": round(fade_margin_db, 1),
        "multipath_outage_pct": round(p_mp, 6),
        "rain_outage_pct": round(p_rain, 6),
        "total_outage_pct": round(outage, 6),
        "availability_pct": round(avail, 5),
        "downtime_minutes_per_year": round(outage / 100.0 * 525_960, 1),
        "nines": _nines_label(avail),
        "rain_zone": rain_zone.upper(),
        "rain_a001_db": round(rain_attenuation_001(d_km, f_ghz, rain_zone), 2),
        "dn1": dn1,
    }
