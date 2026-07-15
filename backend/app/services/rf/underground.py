"""Underground & confined-space propagation: tunnels and through-the-earth.

Two study families that classic DEM-based tools cannot handle at all:

TUNNEL / MINE GALLERY (waveguide regime)
    An electrically-large tunnel behaves as a lossy dielectric waveguide.
    Below the breakpoint distance the link behaves like free space; beyond
    it the dominant (1,1) mode attenuates linearly in dB/m following the
    Emslie/Lagace/Strong approximation for a rectangular tunnel of width
    ``a`` and height ``b`` with wall permittivity eps_r:

        alpha_h [dB/m] = 4.343 * lam^2 * ( eps_r / (a^3*sqrt(eps_r-1))
                                          + 1     / (b^3*sqrt(eps_r-1)) )

    (horizontal polarization; swap the a/b roles for vertical).  The lam^2 /
    a^3 dependence is why UHF propagates for kilometers in tunnels while VHF
    dies within hundreds of meters - the simulator reproduces exactly that.
    Tilt (slope) and roughness add the standard Emslie correction terms.

THROUGH-THE-EARTH (TTE)
    A plane wave in a conductive medium (soil/rock) attenuates with skin
    depth  delta = sqrt(2 / (omega * mu0 * sigma)) ~= 503 / sqrt(f * sigma)
    meters, i.e. 8.686 dB per skin depth.  This is why TTE mine paging and
    cave-rescue links use VLF (sub-10 kHz): at 5 kHz through 0.01 S/m rock
    the skin depth is ~71 m; at 900 MHz it is centimeters.
"""
from __future__ import annotations

import numpy as np

C_LIGHT = 299_792_458.0
MU0 = 4.0e-7 * np.pi

# Wall/rock relative permittivity presets for tunnel studies.
TUNNEL_WALL_PRESETS = {
    "concrete": {"label": "Concrete lining", "eps_r": 6.0},
    "rock": {"label": "Hard rock (granite)", "eps_r": 5.0},
    "coal": {"label": "Coal seam", "eps_r": 4.0},
    "limestone": {"label": "Limestone", "eps_r": 7.0},
    "salt": {"label": "Salt (very low loss)", "eps_r": 4.5},
}

# Ground conductivity presets for TTE studies (S/m).
EARTH_PRESETS = {
    "dry_rock": {"label": "Dry rock / granite", "sigma": 0.001},
    "limestone": {"label": "Limestone (karst)", "sigma": 0.005},
    "average_soil": {"label": "Average soil", "sigma": 0.01},
    "wet_soil": {"label": "Wet soil / clay", "sigma": 0.1},
    "coal_measures": {"label": "Coal measures", "sigma": 0.02},
}


def tunnel_alpha_db_per_m(freq_mhz: float, width_m: float, height_m: float,
                          eps_r: float = 5.0,
                          polarization: str = "horizontal",
                          roughness_m: float = 0.1,
                          tilt_deg: float = 0.0) -> float:
    """Dominant-mode attenuation rate of a rectangular tunnel (dB/m)."""
    lam = C_LIGHT / (freq_mhz * 1e6)
    a, b = (width_m, height_m) if polarization == "horizontal" else (height_m, width_m)
    root = np.sqrt(max(eps_r - 1.0, 0.1))
    alpha = 4.343 * lam ** 2 * (eps_r / (a ** 3 * root) + 1.0 / (b ** 3 * root))
    # Emslie roughness term: 4.343 * pi^2 * h^2 * lam / a^4 (both walls).
    alpha += 4.343 * (np.pi ** 2) * (roughness_m ** 2) * lam * (1.0 / a ** 4 + 1.0 / b ** 4)
    # Tilt term: 4.343 * pi^2 * theta^2 / lam (theta in radians).
    theta = np.radians(abs(tilt_deg))
    alpha += 4.343 * (np.pi ** 2) * theta ** 2 / lam
    return float(alpha)


def tunnel_profile(freq_mhz: float, width_m: float, height_m: float,
                   length_m: float, eps_r: float = 5.0,
                   polarization: str = "horizontal",
                   roughness_m: float = 0.1, tilt_deg: float = 0.0,
                   tx_power_dbm: float = 30.0, tx_gain_dbi: float = 6.0,
                   rx_gain_dbi: float = 0.0, losses_db: float = 0.0,
                   rx_sensitivity_dbm: float = -100.0,
                   coupling_loss_db: float = 25.0,
                   n_samples: int = 200) -> dict:
    """RX power along a tunnel: free-space regime up to the waveguide
    breakpoint, then linear modal attenuation.

    Breakpoint: the distance where the first Fresnel zone fits the tunnel
    cross-section, d_bp ~= max(a,b)^2 / lambda.  ``coupling_loss_db`` is the
    antenna-to-mode insertion loss (typ. 20-30 dB for whip antennas).
    """
    lam = C_LIGHT / (freq_mhz * 1e6)
    alpha = tunnel_alpha_db_per_m(freq_mhz, width_m, height_m, eps_r,
                                  polarization, roughness_m, tilt_deg)
    d_bp = max(width_m, height_m) ** 2 / lam
    d = np.linspace(1.0, max(length_m, 10.0), n_samples)

    fspl = 32.44 + 20.0 * np.log10(d / 1000.0) + 20.0 * np.log10(freq_mhz)
    fspl_bp = 32.44 + 20.0 * np.log10(max(d_bp, 1.0) / 1000.0) + 20.0 * np.log10(freq_mhz)
    # Waveguide regime: loss at breakpoint + coupling + alpha*(d-d_bp).
    waveguide = fspl_bp + coupling_loss_db + alpha * (d - d_bp)
    # Beyond the breakpoint two mechanisms coexist in a straight gallery:
    # the direct ray (plain FSPL, no coupling loss) and the guided mode
    # (coupling + linear alpha).  Whichever loses less carries the link -
    # in low-loss tunnels the mode eventually BEATS free space, which is
    # the measured hallmark of tunnel propagation.
    loss = np.where(d <= d_bp, fspl, np.minimum(waveguide, fspl))

    rx = tx_power_dbm + tx_gain_dbi + rx_gain_dbi - losses_db - loss
    served = rx >= rx_sensitivity_dbm
    max_range = float(d[served][-1]) if served.any() else 0.0
    return {
        "alpha_db_per_m": round(alpha, 4),
        "breakpoint_m": round(float(d_bp), 1),
        "max_range_m": round(max_range, 1),
        "points": [{"d": round(float(di), 1), "rx_power_dbm": round(float(ri), 1),
                    "served": bool(si)}
                   for di, ri, si in zip(d, rx, served)],
    }


def tte_skin_depth_m(freq_hz: float, sigma_s_per_m: float) -> float:
    """Skin depth of a plane wave in a conductive half-space (meters)."""
    omega = 2.0 * np.pi * max(freq_hz, 1.0)
    return float(np.sqrt(2.0 / (omega * MU0 * max(sigma_s_per_m, 1e-6))))


def tte_link(freq_hz: float, depth_m: float, sigma_s_per_m: float,
             tx_power_dbm: float = 30.0, system_gain_db: float = 20.0,
             rx_sensitivity_dbm: float = -130.0) -> dict:
    """Through-the-earth link budget through ``depth_m`` of ground.

    Loss model: conductive attenuation (8.686 dB per skin depth) plus
    quasi-static induction-field spreading — TTE loops couple through the
    magnetic near field, which decays as 1/r^3, i.e. 60*log10(depth)
    relative to 1 m.  ``system_gain_db`` bundles both loop antenna factors.
    """
    delta = tte_skin_depth_m(freq_hz, sigma_s_per_m)
    attenuation = 8.686 * depth_m / delta
    spreading = 60.0 * np.log10(max(depth_m, 1.0))
    total_loss = attenuation + spreading
    rx = tx_power_dbm + system_gain_db - total_loss
    return {
        "skin_depth_m": round(delta, 2),
        "attenuation_db": round(float(attenuation), 1),
        "spreading_db": round(float(spreading), 1),
        "total_loss_db": round(float(total_loss), 1),
        "rx_power_dbm": round(float(rx), 1),
        "margin_db": round(float(rx - rx_sensitivity_dbm), 1),
        "served": bool(rx >= rx_sensitivity_dbm),
    }


# =========================================================================== #
#  Phase 2 — Radiating coaxial cable ("leaky feeder") for metro & mines
# =========================================================================== #
# The dominant real-world solution for continuous radio coverage in tunnels,
# metros and underground mines is NOT free-space waveguide propagation but a
# RADIATING (leaky) coaxial cable run the length of the gallery, periodically
# re-amplified.  Two loss mechanisms set the link:
#
#   * Longitudinal (cable) loss   - dB per 100 m, rising with frequency
#     (conductor skin effect ~ sqrt(f)).  Accumulates along the run.
#   * Coupling loss               - cable -> handset at a reference radial
#     distance (typ. 2 m), the "leak" that makes it an antenna.  Roughly
#     flat with distance along the cable, rising slowly with frequency.
#
# RX(x, r) = P_in(segment) - long_loss*x - coupling_loss(f) - radial(r)
# with radial(r) = 20*log10(r / r_ref) beyond the reference distance.

# Manufacturer-style presets: (loss dB/100 m @ ref freq, coupling dB @2 m,
# reference freq MHz).  Loss scales ~sqrt(f); coupling rises ~5 dB/decade.
LEAKY_CABLE_PRESETS = {
    "rc12_12": {"label": '1-1/4" radiating cable', "loss_db_100m": 2.2,
                "coupling_db": 65.0, "ref_freq_mhz": 450.0},
    "rc78": {"label": '7/8" radiating cable', "loss_db_100m": 3.5,
             "coupling_db": 68.0, "ref_freq_mhz": 450.0},
    "rc12": {"label": '1/2" radiating cable', "loss_db_100m": 5.5,
             "coupling_db": 70.0, "ref_freq_mhz": 450.0},
}


def leaky_cable_loss_db_per_m(freq_mhz: float, loss_db_100m_ref: float,
                              ref_freq_mhz: float = 450.0) -> float:
    """Frequency-scaled longitudinal cable loss (dB/m).  Conductor loss grows
    ~sqrt(f) (skin effect), so we scale the reference dB/100 m accordingly."""
    scale = np.sqrt(max(freq_mhz, 1.0) / max(ref_freq_mhz, 1.0))
    return float(loss_db_100m_ref * scale / 100.0)


def leaky_coupling_loss_db(freq_mhz: float, coupling_db_ref: float,
                           ref_freq_mhz: float = 450.0) -> float:
    """Coupling loss at the reference radial distance, scaled ~5 dB/decade
    with frequency (higher bands couple slightly worse)."""
    return float(coupling_db_ref + 5.0 * np.log10(max(freq_mhz, 1.0)
                                                  / max(ref_freq_mhz, 1.0)))


def amplifier_spacing_m(head_end_dbm: float, design_threshold_dbm: float,
                        coupling_loss_db: float, cable_loss_db_per_m: float,
                        radial_loss_db: float = 0.0) -> float:
    """Maximum run length between inline amplifiers so the tap level never
    drops the reference-distance RX below ``design_threshold_dbm``.

    At the far end of a segment the tap level is lowest; requiring
        head_end - loss*L - coupling - radial >= threshold
    gives  L = (head_end - threshold - coupling - radial) / loss.
    """
    budget = head_end_dbm - design_threshold_dbm - coupling_loss_db - radial_loss_db
    if cable_loss_db_per_m <= 0:
        return float("inf")
    return max(budget / cable_loss_db_per_m, 0.0)


def leaky_feeder_profile(freq_mhz: float, cable_length_m: float,
                         cable: str = "rc78",
                         loss_db_100m: float | None = None,
                         coupling_db: float | None = None,
                         head_end_dbm: float = 20.0,
                         amp_gain_db: float = 30.0,
                         amp_output_dbm: float | None = None,
                         rx_sensitivity_dbm: float = -95.0,
                         design_margin_db: float = 10.0,
                         radial_distance_m: float = 2.0,
                         coupling_reference_m: float = 2.0,
                         auto_amplifiers: bool = True,
                         n_samples: int = 300) -> dict:
    """RX power vs distance along a radiating-cable run, with auto-placed
    inline amplifiers and the "moving-train" continuous-service KPI.

    ``design_threshold_dbm = rx_sensitivity + design_margin`` is the minimum
    acceptable RX at ``radial_distance_m`` from the cable.  Amplifiers are
    inserted (when ``auto_amplifiers``) at the spacing that keeps the tap
    level above threshold; each restores the level to ``amp_output_dbm``
    (default: back to the head-end level), gain-limited by ``amp_gain_db``.
    """
    preset = LEAKY_CABLE_PRESETS.get(cable, LEAKY_CABLE_PRESETS["rc78"])
    ref_f = preset["ref_freq_mhz"]
    loss_ref = loss_db_100m if loss_db_100m is not None else preset["loss_db_100m"]
    coup_ref = coupling_db if coupling_db is not None else preset["coupling_db"]

    loss_m = leaky_cable_loss_db_per_m(freq_mhz, loss_ref, ref_f)
    coupling = leaky_coupling_loss_db(freq_mhz, coup_ref, ref_f)
    radial = 20.0 * np.log10(max(radial_distance_m, coupling_reference_m)
                             / max(coupling_reference_m, 1e-3))
    threshold = rx_sensitivity_dbm + design_margin_db
    if amp_output_dbm is None:
        amp_output_dbm = head_end_dbm

    spacing = amplifier_spacing_m(head_end_dbm, threshold, coupling, loss_m, radial)
    # The amplifier can only restore what its gain allows.
    max_restore_run = amp_gain_db / loss_m if loss_m > 0 else float("inf")
    amp_spacing = min(spacing, max_restore_run) if auto_amplifiers else float("inf")

    d = np.linspace(0.0, max(cable_length_m, 1.0), n_samples)
    amp_positions: list[float] = []
    if auto_amplifiers and np.isfinite(amp_spacing) and amp_spacing > 0:
        pos = amp_spacing
        while pos < cable_length_m:
            amp_positions.append(round(float(pos), 1))
            pos += amp_spacing

    # Tap level along the cable: head-end level minus accumulated loss, reset
    # to amp_output at each amplifier.
    seg_start_level = head_end_dbm
    seg_start_dist = 0.0
    ai = 0
    tap = np.empty_like(d)
    for i, di in enumerate(d):
        while ai < len(amp_positions) and di >= amp_positions[ai]:
            seg_start_level = amp_output_dbm
            seg_start_dist = amp_positions[ai]
            ai += 1
        tap[i] = seg_start_level - loss_m * (di - seg_start_dist)

    rx = tap - coupling - radial
    served = rx >= threshold

    # Moving-train KPI: fraction of the run continuously above threshold, and
    # the worst contiguous gap (m) where a moving receiver would drop.
    served_fraction = float(np.mean(served))
    step = d[1] - d[0] if len(d) > 1 else 0.0
    worst_gap = 0.0
    run = 0.0
    for s in served:
        if not s:
            run += step
            worst_gap = max(worst_gap, run)
        else:
            run = 0.0

    return {
        "cable": cable,
        "cable_loss_db_per_m": round(loss_m, 4),
        "coupling_loss_db": round(coupling, 1),
        "radial_loss_db": round(float(radial), 1),
        "design_threshold_dbm": round(threshold, 1),
        "amplifier_spacing_m": round(float(amp_spacing), 1)
        if np.isfinite(amp_spacing) else None,
        "amplifier_positions_m": amp_positions,
        "amplifier_count": len(amp_positions),
        "amplifier_gain_required_db": round(min(loss_m * amp_spacing, amp_gain_db), 1)
        if np.isfinite(amp_spacing) else None,
        "continuous_service_pct": round(served_fraction * 100.0, 1),
        "worst_gap_m": round(worst_gap, 1),
        "moving_train_ok": bool(worst_gap == 0.0),
        "points": [{"d": round(float(di), 1), "rx_power_dbm": round(float(ri), 1),
                    "served": bool(si)}
                   for di, ri, si in zip(d, rx, served)],
    }
