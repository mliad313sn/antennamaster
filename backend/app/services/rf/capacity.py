"""Traffic & capacity dimensioning: Erlang B/C + SINR→MCS→throughput.

Closes the "coverage but no capacity" gap:

ERLANG B / C — the classic circuit-dimensioning formulas (PMR/TETRA voice,
trunked channels): blocking probability for offered traffic over N channels
(Erlang B, blocked-calls-cleared), waiting probability (Erlang C,
blocked-calls-queued), and the inverse — how many channels a grade of service
requires.  Computed with the numerically stable recurrence, exact for large N.

SINR → THROUGHPUT — maps a SINR field (from the multi-site / frequency-plan
engines) to spectral efficiency via the 3GPP TS 38.214 CQI table (15 entries,
64-QAM table efficiencies) using the standard published SINR switching
thresholds, then to Mbit/s with the channel bandwidth and an overhead factor.
Cell capacity aggregates the served pixels under a round-robin assumption
(each pixel gets an equal share of airtime — documented, conservative).

SATURATION — offered load (users × Mbit/s per user) against cell capacity:
load factor, saturated flag, and the maximum users the cell can carry.
"""
from __future__ import annotations

import math

import numpy as np

# 3GPP TS 38.214 Table 5.2.2.1-2 (CQI 1..15) efficiencies in bit/s/Hz, with
# the standard published link-level SINR switching thresholds (dB).
CQI_TABLE: list[tuple[float, float]] = [
    (-6.7, 0.1523), (-4.7, 0.2344), (-2.3, 0.3770), (0.2, 0.6016),
    (2.4, 0.8770), (4.3, 1.1758), (5.9, 1.4766), (8.1, 1.9141),
    (10.3, 2.4063), (11.7, 2.7305), (14.1, 3.3223), (16.3, 3.9023),
    (18.7, 4.5234), (21.0, 5.1152), (22.7, 5.5547),
]


# ------------------------------------------------------------------ Erlang
def erlang_b(traffic_erlangs: float, channels: int) -> float:
    """Blocking probability, blocked-calls-cleared (numerically stable)."""
    if traffic_erlangs < 0 or channels < 0:
        raise ValueError("traffic and channels must be non-negative")
    if channels == 0:
        return 1.0
    b = 1.0
    for n in range(1, channels + 1):
        b = traffic_erlangs * b / (n + traffic_erlangs * b)
    return float(b)


def erlang_c(traffic_erlangs: float, channels: int) -> float:
    """Probability a call waits, blocked-calls-delayed (M/M/N queue).
    Defined for offered traffic < channels; returns 1.0 at/beyond saturation."""
    a, n = traffic_erlangs, channels
    if a <= 0:
        return 0.0
    if n <= a:
        return 1.0
    b = erlang_b(a, n)
    return float(n * b / (n - a * (1.0 - b)))


def channels_for_gos(traffic_erlangs: float, gos: float,
                     kind: str = "b", max_channels: int = 10_000) -> int:
    """Smallest channel count meeting the grade of service (blocking ≤ gos)."""
    fn = erlang_b if kind == "b" else erlang_c
    for n in range(1, max_channels + 1):
        if fn(traffic_erlangs, n) <= gos:
            return n
    raise ValueError("grade of service unreachable within max_channels")


# ------------------------------------------------------- SINR -> throughput
def spectral_efficiency(sinr_db) -> np.ndarray:
    """bit/s/Hz per the 3GPP CQI ladder; 0 below CQI-1, capped at CQI-15."""
    s = np.asarray(sinr_db, dtype=np.float64)
    eff = np.zeros(s.shape)
    for thr, e in CQI_TABLE:
        eff[s >= thr] = e
    return eff


def throughput_map_mbps(sinr_db, bandwidth_mhz: float,
                        overhead: float = 0.25) -> np.ndarray:
    """Per-pixel achievable throughput (Mbit/s) at full airtime."""
    if not (0.0 <= overhead < 1.0):
        raise ValueError("overhead must be in [0, 1)")
    eff = spectral_efficiency(sinr_db)
    return eff * bandwidth_mhz * (1.0 - overhead)


def cell_capacity(sinr_db_field, served_mask, bandwidth_mhz: float,
                  overhead: float = 0.25) -> dict:
    """Aggregate capacity of one cell under round-robin airtime sharing.

    With equal airtime per served pixel, the cell's aggregate throughput is
    the *harmonic-style mean* of per-pixel rates — here reported both ways:
    ``capacity_mbps`` (equal-airtime aggregate) and ``peak_mbps``.
    """
    tp = throughput_map_mbps(sinr_db_field, bandwidth_mhz, overhead)
    served = tp[np.asarray(served_mask, dtype=bool) & (tp > 0)]
    if served.size == 0:
        return {"capacity_mbps": 0.0, "peak_mbps": 0.0, "edge_mbps": 0.0,
                "served_pixels": 0}
    # Equal airtime share: aggregate = N / sum(1/r_i) is the equal-throughput
    # capacity; equal-airtime aggregate is simply mean(r_i).  We report the
    # equal-airtime mean (each user gets rate r_i * 1/N of the time).
    return {
        "capacity_mbps": round(float(served.mean()), 1),
        "peak_mbps": round(float(served.max()), 1),
        "edge_mbps": round(float(np.percentile(served, 5)), 1),
        "served_pixels": int(served.size),
    }


def saturation(capacity_mbps: float, users: int,
               mbps_per_user: float) -> dict:
    """Offered load vs capacity: load factor, verdict, headroom."""
    demand = users * mbps_per_user
    load = demand / capacity_mbps if capacity_mbps > 0 else math.inf
    return {
        "demand_mbps": round(demand, 1),
        "load_factor": round(load, 3) if math.isfinite(load) else None,
        "saturated": bool(load > 1.0),
        "max_users": int(capacity_mbps // mbps_per_user)
        if mbps_per_user > 0 and capacity_mbps > 0 else 0,
    }
