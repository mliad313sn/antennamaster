"""Environmental excess-loss models: foliage, rain, atmospheric gases.

These stack on top of any propagation model + terrain diffraction, covering
the field scenarios pure terrain physics misses:

FOLIAGE / VEGETATION (last-mile clutter)
    Weissberger's Modified Exponential Decay model - the widely used
    vegetation-depth model for 230 MHz-95 GHz through dense, in-leaf trees:
        d <= 14 m :  L = 0.45 * f_GHz^0.284 * d
        d >  400 m:  clamped at d = 400 m (model validity limit)
        else      :  L = 1.33 * f_GHz^0.284 * d^0.588
    Used as the "foliage depth at the receiver" knob for wooded/industrial
    last-mile studies (the role ITU-R P.833 plays in commercial tools).

RAIN (ITU-R P.838 coefficients + effective path)
    Specific attenuation gamma_R = k * R^alpha (dB/km) with k, alpha
    log-interpolated from the P.838-3 horizontal-polarization table
    (1-100 GHz).  Combined with an ITU-R P.530-style effective path length
    d_eff = d / (1 + d / d0), d0 = 35 * exp(-0.015 * R), so long links are
    not over-penalized (rain cells are finite).

ATMOSPHERIC GASES (ITU-R P.676 approximation)
    Sea-level specific attenuation for dry air + water vapour (7.5 g/m3)
    from the standard simplified fits; significant above ~10 GHz and
    dominated by the 22.2 GHz water-vapour and 60 GHz oxygen lines.
"""
from __future__ import annotations

import numpy as np

# ITU-R P.838-3 coefficients, horizontal polarization: freq_GHz -> (k, alpha)
_P838 = [
    (1.0, 0.0000259, 0.9691), (2.0, 0.0000847, 1.0664),
    (4.0, 0.0001071, 1.6009), (6.0, 0.0007056, 1.5900),
    (8.0, 0.004115, 1.3905), (10.0, 0.01217, 1.2571),
    (12.0, 0.02386, 1.1825), (15.0, 0.04481, 1.1233),
    (20.0, 0.09164, 1.0568), (25.0, 0.1571, 0.9991),
    (30.0, 0.2403, 0.9485), (35.0, 0.3374, 0.9047),
    (40.0, 0.4431, 0.8673), (50.0, 0.6600, 0.8084),
    (60.0, 0.8606, 0.7656), (70.0, 1.0315, 0.7345),
    (80.0, 1.1704, 0.7115), (100.0, 1.3671, 0.6815),
]


def foliage_loss_db(freq_mhz: float, depth_m: float) -> float:
    """Weissberger MED vegetation loss for `depth_m` of dense foliage."""
    if depth_m <= 0:
        return 0.0
    f_ghz = max(freq_mhz / 1000.0, 0.23)
    d = min(depth_m, 400.0)                      # model validity ceiling
    if d <= 14.0:
        return float(0.45 * f_ghz ** 0.284 * d)
    return float(1.33 * f_ghz ** 0.284 * d ** 0.588)


def rain_specific_attenuation(freq_mhz: float, rain_rate_mm_h: float) -> float:
    """gamma_R = k * R^alpha in dB/km (ITU-R P.838-3, horizontal pol.)."""
    if rain_rate_mm_h <= 0:
        return 0.0
    f = float(np.clip(freq_mhz / 1000.0, _P838[0][0], _P838[-1][0]))
    fs = np.array([r[0] for r in _P838])
    ks = np.array([r[1] for r in _P838])
    als = np.array([r[2] for r in _P838])
    # k varies over orders of magnitude: interpolate log(k) vs log(f).
    k = float(np.exp(np.interp(np.log(f), np.log(fs), np.log(ks))))
    alpha = float(np.interp(np.log(f), np.log(fs), als))
    return k * rain_rate_mm_h ** alpha


def rain_loss_db(freq_mhz: float, dist_m: float, rain_rate_mm_h: float) -> float:
    """Rain attenuation over the link using the P.530 effective path length."""
    if rain_rate_mm_h <= 0 or dist_m <= 0:
        return 0.0
    gamma = rain_specific_attenuation(freq_mhz, rain_rate_mm_h)
    d_km = dist_m / 1000.0
    d0 = 35.0 * np.exp(-0.015 * min(rain_rate_mm_h, 100.0))
    d_eff = d_km / (1.0 + d_km / d0)
    return float(gamma * d_eff)


def gaseous_attenuation_db_per_km(freq_mhz: float,
                                  water_vapour_g_m3: float = 7.5) -> float:
    """Sea-level specific gaseous attenuation (dry air + water vapour),
    simplified ITU-R P.676 fits, valid ~1-100 GHz away from line centers."""
    f = max(freq_mhz / 1000.0, 0.1)              # GHz
    # Dry air (oxygen): flat ~0.0067 below 10 GHz rising into the 60 GHz line.
    gamma_o = (7.2 / (f ** 2 + 0.34) + 0.62 / ((54.0 - f) ** 1.16 + 0.83)) \
        * f ** 2 * 1e-3 if f < 54 else 15.0      # inside the O2 complex: huge
    # Water vapour (rho = 7.5 g/m3 standard), 22.235 GHz line dominant.
    rho = water_vapour_g_m3
    gamma_w = (0.046 + 0.0019 * rho
               + 3.98 * (1 + 0.006 * rho) / ((f - 22.235) ** 2 + 9.42)
               ) * f ** 2 * rho * 1e-4
    return float(gamma_o + gamma_w)


def thermal_sensitivity_dbm(bandwidth_mhz: float, noise_figure_db: float,
                            target_sinr_db: float) -> float:
    """Receiver sensitivity from first principles:
    kTB (-174 dBm/Hz) + 10log10(BW) + NF + required SINR.
    This is how LTE/5G channel-width scaling is handled: a 100 MHz NR
    carrier needs 10 dB more power than a 10 MHz one for the same SINR."""
    return float(-174.0 + 10.0 * np.log10(max(bandwidth_mhz, 0.001) * 1e6)
                 + noise_figure_db + target_sinr_db)
