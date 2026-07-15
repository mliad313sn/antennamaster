"""Leaky-feeder (radiating cable) & distributed-antenna tunnel coverage.

The straight-waveguide model in ``underground.py`` explains why UHF outranges
VHF in a bare gallery, but it is NOT how real metros and underground mines are
covered.  Those use either a **radiating ("leaky") coaxial cable** run along
the tunnel, or a **distributed antenna system (DAS)** of tunnel antennas.  This
module models both, which is the actual deliverable for a metro line or a deep
mine -- a domain the mainstream DEM planners barely touch.

RADIATING CABLE
    A leaky feeder loses power two ways:

      * longitudinal loss  alpha  [dB/m] -- power travelling *along* the cable,
        frequency-dependent (vendor "attenuation" figure, dB/100 m);
      * coupling loss  Lc  [dB]   -- cable -> portable at a reference lateral
        distance (typ. 2 m), the "how much leaks out" figure (typ. 60-75 dB).

    Field level at a portable ``lateral`` metres from the cable, a distance
    ``x`` along it from the head end (with periodic inline amplifiers of gain
    ``G`` every ``S`` metres restoring the longitudinal loss)::

        cable_level(x) = P0 + floor((x)/S)*G - alpha*x
        field(x)       = cable_level(x) - Lc - 20*log10(lateral/ref)

    The design solves amplifier spacing so the field never drops below the
    portable sensitivity plus a system margin over the whole run.

DISTRIBUTED TUNNEL ANTENNAS
    Discrete antennas on the tunnel centreline, each radiating into the
    Emslie waveguide (reusing ``underground.py``); per-antenna reach sets the
    spacing for continuous service.  The metro KPI -- served length fraction
    and worst-case gap -- falls straight out.

BENDS & JUNCTIONS
    Real galleries curve and branch.  A bend past the line-of-sight of the
    radiating element adds excess loss that grows with frequency and with the
    tightness of the bend (small radius-to-width ratio); junctions split power.
    Modelled as a documented per-feature excess-loss term on top of the
    straight-section physics.
"""
from __future__ import annotations

import numpy as np

from .underground import tunnel_alpha_db_per_m

C_LIGHT = 299_792_458.0


def coupling_loss_at(coupling_ref_db: float, lateral_m: float,
                     ref_m: float = 2.0) -> float:
    """Coupling loss at ``lateral_m`` from a reference figure quoted at ``ref_m``.

    Beyond the reference distance the near field falls ~20 dB/decade, so the
    extra loss is 20*log10(lateral/ref); inside the reference distance the
    quoted coupling loss is held (no unphysical gain)."""
    return coupling_ref_db + 20.0 * np.log10(max(lateral_m, 0.1) / ref_m) \
        if lateral_m > ref_m else coupling_ref_db


def tunnel_bend_loss_db(freq_mhz: float, width_m: float,
                        radius_m: float, angle_deg: float = 90.0) -> float:
    """Excess loss of a curved tunnel section (documented approximation).

    A bend takes the receiver out of the incident mode's line of sight; the
    loss grows with electrical size (freq * width / radius) and bend angle.
    Approximation: L = k * (freq_ghz * width / radius) * (angle/90), with a
    modest floor so a gentle sweep is not free.  Tight, high-frequency bends
    in narrow tunnels are correctly the most lossy."""
    f_ghz = freq_mhz / 1000.0
    ratio = f_ghz * max(width_m, 0.5) / max(radius_m, 1.0)
    loss = 12.0 * ratio * (max(angle_deg, 0.0) / 90.0)
    return float(min(max(loss, 1.0), 40.0))


def leaky_feeder_amp_spacing_m(cable_atten_db_per_100m: float,
                               amp_gain_db: float) -> float:
    """Amplifier spacing that exactly restores the longitudinal span loss:
    each amp of gain G covers a run over which the cable loses G dB."""
    alpha = cable_atten_db_per_100m / 100.0
    if alpha <= 0:
        return float("inf")
    return float(amp_gain_db / alpha)


def leaky_feeder_profile(freq_mhz: float, length_m: float,
                         cable_atten_db_per_100m: float,
                         coupling_ref_db: float = 65.0,
                         coupling_ref_m: float = 2.0,
                         lateral_m: float = 2.0,
                         tx_power_dbm: float = 20.0,
                         rx_sensitivity_dbm: float = -95.0,
                         system_margin_db: float = 10.0,
                         amp_gain_db: float = 0.0,
                         amp_spacing_m: float | None = None,
                         bends: list[dict] | None = None,
                         n_samples: int = 300) -> dict:
    """Field level along a radiating cable, with optional inline amplifiers
    and bend losses; reports served length and worst uncovered gap.

    ``amp_gain_db`` > 0 with ``amp_spacing_m`` = None auto-solves the spacing
    that restores the span loss.  ``bends`` is a list of
    ``{"position_m", "radius_m", "angle_deg"}`` excess-loss features.
    """
    alpha = cable_atten_db_per_100m / 100.0                  # dB/m
    x = np.linspace(0.0, max(length_m, 1.0), n_samples)

    # Inline amplifier gain accumulated up to each x.
    if amp_gain_db > 0.0:
        if amp_spacing_m is None:
            amp_spacing_m = leaky_feeder_amp_spacing_m(
                cable_atten_db_per_100m, amp_gain_db)
        n_amps = np.floor(x / max(amp_spacing_m, 1.0))
        amp_boost = n_amps * amp_gain_db
    else:
        amp_spacing_m = None
        amp_boost = np.zeros_like(x)

    cable_level = tx_power_dbm + amp_boost - alpha * x

    # Bend excess loss: cumulative past each bend position.
    bend_loss = np.zeros_like(x)
    for b in (bends or []):
        pos = float(b["position_m"])
        bl = tunnel_bend_loss_db(freq_mhz, b.get("width_m", 5.0),
                                 float(b.get("radius_m", 30.0)),
                                 float(b.get("angle_deg", 90.0)))
        bend_loss += np.where(x >= pos, bl, 0.0)

    lc = coupling_loss_at(coupling_ref_db, lateral_m, coupling_ref_m)
    field = cable_level - lc - bend_loss
    required = rx_sensitivity_dbm + system_margin_db
    served = field >= required

    # Worst uncovered gap length (metres) and served fraction.
    dx = x[1] - x[0] if len(x) > 1 else 0.0
    served_frac = float(np.mean(served))
    worst_gap = 0.0
    run = 0.0
    for ok in served:
        run = 0.0 if ok else run + dx
        worst_gap = max(worst_gap, run)
    max_range = float(x[served][-1]) if served.any() else 0.0
    return {
        "alpha_db_per_m": round(alpha, 4),
        "coupling_loss_db": round(float(lc), 1),
        "amp_spacing_m": round(float(amp_spacing_m), 1) if amp_spacing_m else None,
        "amps_required": int(np.floor(length_m / amp_spacing_m)) if amp_spacing_m else 0,
        "required_field_dbm": round(float(required), 1),
        "served_length_fraction": round(served_frac, 4),
        "continuous_service": bool(worst_gap == 0.0 and served.any()),
        "worst_gap_m": round(worst_gap, 1),
        "reliable_range_m": round(max_range, 1),
        "end_field_dbm": round(float(field[-1]), 1),
        "points": [{"x_m": round(float(xi), 1),
                    "field_dbm": round(float(fi), 1), "served": bool(si)}
                   for xi, fi, si in zip(x, field, served)],
    }


def distributed_antenna_tunnel(freq_mhz: float, width_m: float, height_m: float,
                               length_m: float, eps_r: float = 5.0,
                               tx_power_dbm: float = 20.0,
                               tx_gain_dbi: float = 3.0, rx_gain_dbi: float = 0.0,
                               losses_db: float = 0.0,
                               rx_sensitivity_dbm: float = -95.0,
                               coupling_loss_db: float = 25.0,
                               overlap_pct: float = 15.0,
                               polarization: str = "horizontal",
                               roughness_m: float = 0.1,
                               tilt_deg: float = 0.0) -> dict:
    """Distributed-antenna design for a straight gallery: single-antenna reach
    (Emslie waveguide), then spacing/count for continuous coverage.

    Each antenna radiates both ways along the tunnel; its one-sided reach is
    the distance at which the guided-mode field drops to the sensitivity.
    Antennas are spaced with ``overlap_pct`` hand-off between neighbours.
    """
    lam = C_LIGHT / (freq_mhz * 1e6)
    alpha = tunnel_alpha_db_per_m(freq_mhz, width_m, height_m, eps_r,
                                  polarization, roughness_m, tilt_deg)
    d_bp = max(width_m, height_m) ** 2 / lam
    # Budget available to the guided mode past the breakpoint.
    eirp = tx_power_dbm + tx_gain_dbi + rx_gain_dbi - losses_db
    fspl_bp = 32.44 + 20.0 * np.log10(max(d_bp, 1.0) / 1000.0) \
        + 20.0 * np.log10(freq_mhz)
    budget = eirp - fspl_bp - coupling_loss_db - rx_sensitivity_dbm
    # One-sided reach: distance past the breakpoint the mode can still be heard.
    reach = d_bp + max(budget, 0.0) / alpha if alpha > 0 else length_m
    reach = max(reach, d_bp)

    overlap = max(0.0, min(overlap_pct, 90.0)) / 100.0
    spacing = 2.0 * reach * (1.0 - overlap)
    count = max(1, int(np.ceil(length_m / max(spacing, 1.0))))
    positions = [round((i + 0.5) * length_m / count, 1) for i in range(count)]
    return {
        "alpha_db_per_m": round(alpha, 4),
        "single_antenna_reach_m": round(float(reach), 1),
        "antenna_spacing_m": round(float(spacing), 1),
        "antennas_required": count,
        "positions_m": positions,
        "continuous_service": True,
        "overlap_pct": overlap_pct,
    }
