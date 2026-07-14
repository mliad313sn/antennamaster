"""Path-loss / propagation models for all supported radio studies.

Implemented models (chosen to cover every mainstream technology era):

* ``fspl``          - Free Space Path Loss (ITU-R P.525). Any frequency.
                      Microwave PtP, satellite, baseline for all others.
* ``okumura_hata``  - Okumura-Hata empirical model, 150-1500 MHz.
                      Classic macro-cell model for GSM900 / 2G / PMR / paging.
* ``cost231_hata``  - COST-231 extension of Hata, 1500-2000 MHz.
                      GSM1800 / DCS / early UMTS planning.
* ``tr38901_rma``   - 3GPP TR 38.901 Rural Macro (LOS/NLOS), 0.5-30 GHz.
* ``tr38901_uma``   - 3GPP TR 38.901 Urban Macro (LOS/NLOS), 0.5-100 GHz.
                      The standard 4G LTE / 5G NR planning model.
* ``tr38901_umi``   - 3GPP TR 38.901 Urban Micro street canyon (LOS/NLOS),
                      0.5-100 GHz. Small cells / mmWave 5G.

Every model returns *median* path loss in dB for arrays of 2D distances.
Terrain-aware diffraction (single or Deygout multi-edge, computed on the
k=4/3 curved fused profile) is ADDED on top by the callers, which is how the
simulator stays honest in mountainous terrain where pure empirical models
fail.  Out-of-validity inputs are clamped and reported as warnings rather
than rejected, matching how commercial planning tools behave.
"""
from __future__ import annotations

import numpy as np

C_LIGHT = 299_792_458.0

# Registry: key -> (label, f_min_mhz, f_max_mhz, description)
MODEL_INFO: dict[str, dict] = {
    "fspl": {
        "label": "Free space (ITU-R P.525)",
        "f_range_mhz": [1.0, 300_000.0],
        "environments": [],
        "description": "Ideal free-space loss; baseline and microwave PtP links.",
    },
    "okumura_hata": {
        "label": "Okumura-Hata (150-1500 MHz)",
        "f_range_mhz": [150.0, 1500.0],
        "environments": ["urban", "suburban", "open"],
        "description": "Empirical macro-cell model: GSM900, TETRA, PMR, FM/TV.",
    },
    "cost231_hata": {
        "label": "COST-231 Hata (1500-2000 MHz)",
        "f_range_mhz": [1500.0, 2000.0],
        "environments": ["urban", "metropolitan", "suburban", "open"],
        "description": "Hata extension: GSM1800/DCS, UMTS2100 approximation.",
    },
    "tr38901_rma": {
        "label": "3GPP TR 38.901 RMa (rural macro)",
        "f_range_mhz": [500.0, 30_000.0],
        "environments": ["los", "nlos"],
        "description": "4G/5G rural macro cells.",
    },
    "tr38901_uma": {
        "label": "3GPP TR 38.901 UMa (urban macro)",
        "f_range_mhz": [500.0, 100_000.0],
        "environments": ["los", "nlos"],
        "description": "4G LTE / 5G NR urban macro; valid to 100 GHz.",
    },
    "tr38901_umi": {
        "label": "3GPP TR 38.901 UMi (street canyon)",
        "f_range_mhz": [500.0, 100_000.0],
        "environments": ["los", "nlos"],
        "description": "Small cells and mmWave 5G street-level deployments.",
    },
}


def fspl_db(d_m: np.ndarray, f_mhz: float) -> np.ndarray:
    """Free-space path loss (dB); d in meters, f in MHz."""
    d_km = np.maximum(np.asarray(d_m, dtype=np.float64), 1.0) / 1000.0
    return 32.44 + 20.0 * np.log10(d_km) + 20.0 * np.log10(f_mhz)


def _hata_a_hm(f_mhz: float, h_m: float, metropolitan: bool) -> float:
    """Mobile-antenna correction factor a(hm) for Hata-family models."""
    if metropolitan and f_mhz >= 300.0:
        return 3.2 * (np.log10(11.75 * h_m)) ** 2 - 4.97
    if metropolitan:
        return 8.29 * (np.log10(1.54 * h_m)) ** 2 - 1.1
    lf = np.log10(f_mhz)
    return (1.1 * lf - 0.7) * h_m - (1.56 * lf - 0.8)


def okumura_hata_db(d_m: np.ndarray, f_mhz: float, h_bs_m: float, h_ut_m: float,
                    environment: str = "urban") -> np.ndarray:
    """Okumura-Hata median path loss.  Validity: 150-1500 MHz, hb 30-200 m,
    hm 1-10 m, d 1-20 km (inputs are clamped to those ranges)."""
    f = float(np.clip(f_mhz, 150.0, 1500.0))
    hb = float(np.clip(h_bs_m, 30.0, 200.0))
    hm = float(np.clip(h_ut_m, 1.0, 10.0))
    d_km = np.clip(np.asarray(d_m, dtype=np.float64) / 1000.0, 0.02, 100.0)

    a_hm = _hata_a_hm(f, hm, metropolitan=False)
    L = (69.55 + 26.16 * np.log10(f) - 13.82 * np.log10(hb) - a_hm
         + (44.9 - 6.55 * np.log10(hb)) * np.log10(d_km))
    if environment == "suburban":
        L -= 2.0 * (np.log10(f / 28.0)) ** 2 + 5.4
    elif environment == "open":
        L -= 4.78 * (np.log10(f)) ** 2 - 18.33 * np.log10(f) + 40.94
    return L


def cost231_hata_db(d_m: np.ndarray, f_mhz: float, h_bs_m: float, h_ut_m: float,
                    environment: str = "urban") -> np.ndarray:
    """COST-231 Hata median path loss, 1500-2000 MHz."""
    f = float(np.clip(f_mhz, 1500.0, 2000.0))
    hb = float(np.clip(h_bs_m, 30.0, 200.0))
    hm = float(np.clip(h_ut_m, 1.0, 10.0))
    d_km = np.clip(np.asarray(d_m, dtype=np.float64) / 1000.0, 0.02, 100.0)

    metropolitan = environment == "metropolitan"
    a_hm = _hata_a_hm(f, hm, metropolitan=metropolitan)
    cm = 3.0 if metropolitan else 0.0
    L = (46.3 + 33.9 * np.log10(f) - 13.82 * np.log10(hb) - a_hm
         + (44.9 - 6.55 * np.log10(hb)) * np.log10(d_km) + cm)
    if environment == "suburban":
        L -= 2.0 * (np.log10(f / 28.0)) ** 2 + 5.4
    elif environment == "open":
        L -= 4.78 * (np.log10(f)) ** 2 - 18.33 * np.log10(f) + 40.94
    return L


# ------------------------------------------------------------ 3GPP TR 38.901
def _d3d(d2d_m: np.ndarray, h_bs_m: float, h_ut_m: float) -> np.ndarray:
    return np.sqrt(np.square(d2d_m) + (h_bs_m - h_ut_m) ** 2)


def tr38901_uma_db(d_m: np.ndarray, f_mhz: float, h_bs_m: float, h_ut_m: float,
                   environment: str = "nlos") -> np.ndarray:
    """3GPP TR 38.901 §7.4.1 Urban Macro path loss (LOS or NLOS)."""
    fc = f_mhz / 1000.0                                    # GHz
    d2d = np.maximum(np.asarray(d_m, dtype=np.float64), 10.0)
    d3d = _d3d(d2d, h_bs_m, h_ut_m)
    # Effective antenna heights (h_E = 1 m assumption for hUT < 13 m).
    hbs_e, hut_e = h_bs_m - 1.0, max(h_ut_m - 1.0, 0.5)
    d_bp = 4.0 * hbs_e * hut_e * fc * 1e9 / C_LIGHT

    pl1 = 28.0 + 22.0 * np.log10(d3d) + 20.0 * np.log10(fc)
    pl2 = (28.0 + 40.0 * np.log10(d3d) + 20.0 * np.log10(fc)
           - 9.0 * np.log10(d_bp ** 2 + (h_bs_m - h_ut_m) ** 2))
    los = np.where(d2d <= d_bp, pl1, pl2)
    if environment == "los":
        return los
    nlos = (13.54 + 39.08 * np.log10(d3d) + 20.0 * np.log10(fc)
            - 0.6 * (h_ut_m - 1.5))
    return np.maximum(los, nlos)


def tr38901_umi_db(d_m: np.ndarray, f_mhz: float, h_bs_m: float, h_ut_m: float,
                   environment: str = "nlos") -> np.ndarray:
    """3GPP TR 38.901 §7.4.1 Urban Micro street-canyon path loss."""
    fc = f_mhz / 1000.0
    d2d = np.maximum(np.asarray(d_m, dtype=np.float64), 10.0)
    d3d = _d3d(d2d, h_bs_m, h_ut_m)
    hbs_e, hut_e = h_bs_m - 1.0, max(h_ut_m - 1.0, 0.5)
    d_bp = 4.0 * hbs_e * hut_e * fc * 1e9 / C_LIGHT

    pl1 = 32.4 + 21.0 * np.log10(d3d) + 20.0 * np.log10(fc)
    pl2 = (32.4 + 40.0 * np.log10(d3d) + 20.0 * np.log10(fc)
           - 9.5 * np.log10(d_bp ** 2 + (h_bs_m - h_ut_m) ** 2))
    los = np.where(d2d <= d_bp, pl1, pl2)
    if environment == "los":
        return los
    nlos = (35.3 * np.log10(d3d) + 22.4 + 21.3 * np.log10(fc)
            - 0.3 * (h_ut_m - 1.5))
    return np.maximum(los, nlos)


def tr38901_rma_db(d_m: np.ndarray, f_mhz: float, h_bs_m: float, h_ut_m: float,
                   environment: str = "nlos") -> np.ndarray:
    """3GPP TR 38.901 §7.4.1 Rural Macro path loss (h=5 m buildings, W=20 m)."""
    fc = f_mhz / 1000.0
    h, w = 5.0, 20.0                                       # TR 38.901 defaults
    d2d = np.maximum(np.asarray(d_m, dtype=np.float64), 10.0)
    d3d = _d3d(d2d, h_bs_m, h_ut_m)
    d_bp = 2.0 * np.pi * h_bs_m * h_ut_m * fc * 1e9 / C_LIGHT

    pl1 = (20.0 * np.log10(40.0 * np.pi * d3d * fc / 3.0)
           + min(0.03 * h ** 1.72, 10.0) * np.log10(d3d)
           - min(0.044 * h ** 1.72, 14.77) + 0.002 * np.log10(h) * d3d)
    pl_bp = (20.0 * np.log10(40.0 * np.pi * d_bp * fc / 3.0)
             + min(0.03 * h ** 1.72, 10.0) * np.log10(d_bp)
             - min(0.044 * h ** 1.72, 14.77) + 0.002 * np.log10(h) * d_bp)
    pl2 = pl_bp + 40.0 * np.log10(d3d / d_bp)
    los = np.where(d2d <= d_bp, pl1, pl2)
    if environment == "los":
        return los
    nlos = (161.04 - 7.1 * np.log10(w) + 7.5 * np.log10(h)
            - (24.37 - 3.7 * (h / h_bs_m) ** 2) * np.log10(h_bs_m)
            + (43.42 - 3.1 * np.log10(h_bs_m)) * (np.log10(d3d) - 3.0)
            + 20.0 * np.log10(fc)
            - (3.2 * (np.log10(11.75 * h_ut_m)) ** 2 - 4.97))
    return np.maximum(los, nlos)


_MODEL_FUNCS = {
    "fspl": lambda d, f, hb, hu, env: fspl_db(d, f),
    "okumura_hata": okumura_hata_db,
    "cost231_hata": cost231_hata_db,
    "tr38901_rma": tr38901_rma_db,
    "tr38901_uma": tr38901_uma_db,
    "tr38901_umi": tr38901_umi_db,
}


def path_loss_db(model: str, d_m: np.ndarray, f_mhz: float,
                 h_bs_m: float, h_ut_m: float, environment: str = "urban",
                 ) -> tuple[np.ndarray, list[str]]:
    """Dispatch to a model; returns (loss_db, warnings)."""
    if model not in _MODEL_FUNCS:
        raise ValueError(f"Unknown propagation model: {model!r}")
    warnings: list[str] = []
    lo, hi = MODEL_INFO[model]["f_range_mhz"]
    if not lo <= f_mhz <= hi:
        warnings.append(
            f"{f_mhz:g} MHz is outside the validity range of {model} "
            f"({lo:g}-{hi:g} MHz); frequency was clamped - consider a different model.")
    loss = _MODEL_FUNCS[model](np.asarray(d_m, dtype=np.float64),
                               f_mhz, h_bs_m, h_ut_m, environment)
    # No model returns less than free-space loss in the real world.
    return np.maximum(loss, fspl_db(d_m, f_mhz)), warnings


# ------------------------------------------------------- Deygout diffraction
def _v_params(d: np.ndarray, e: np.ndarray, i0: int, i1: int, lam: float) -> np.ndarray:
    """Fresnel-Kirchhoff v for every sample strictly between i0 and i1,
    relative to the straight line joining profile samples i0 and i1."""
    dseg = d[i0 + 1:i1] - d[i0]
    total = d[i1] - d[i0]
    los = e[i0] + (e[i1] - e[i0]) * dseg / total
    h = e[i0 + 1:i1] - los
    d1 = np.maximum(dseg, 1.0)
    d2 = np.maximum(total - dseg, 1.0)
    return h * np.sqrt(2.0 * (d1 + d2) / (lam * d1 * d2))


def _ke_loss(v: float) -> float:
    if v <= -0.78:
        return 0.0
    return float(6.9 + 20.0 * np.log10(np.sqrt((v - 0.1) ** 2 + 1.0) + v - 0.1))


def ke_loss_array(v: np.ndarray) -> np.ndarray:
    """Vectorized ITU-R P.526 knife-edge loss for arrays of v (0 below -0.78)."""
    v = np.asarray(v, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        loss = 6.9 + 20.0 * np.log10(np.sqrt((v - 0.1) ** 2 + 1.0) + v - 0.1)
    return np.where(v > -0.78, loss, 0.0)


def deygout_loss_db(distances_m: np.ndarray, elevations_m: np.ndarray,
                    tx_h_m: float, rx_h_m: float, freq_mhz: float,
                    max_edges: int = 3) -> float:
    """Deygout multiple-knife-edge diffraction loss over a (curved) profile.

    The strongest edge (max v) is evaluated against the direct TX-RX line,
    then the method recurses on the two sub-paths, up to ``max_edges`` edges.
    Elevations must already include the earth-curvature bulge.
    """
    lam = C_LIGHT / (freq_mhz * 1e6)
    e = np.asarray(elevations_m, dtype=np.float64).copy()
    e[0] += tx_h_m
    e[-1] += rx_h_m
    d = np.asarray(distances_m, dtype=np.float64)

    def recurse(i0: int, i1: int, budget: int) -> float:
        if budget <= 0 or i1 - i0 < 2:
            return 0.0
        v = _v_params(d, e, i0, i1, lam)
        k = int(np.argmax(v))
        v_max = float(v[k])
        if v_max <= -0.78:
            return 0.0
        loss = _ke_loss(v_max)
        # Only split around a genuinely obstructing edge (v > 0).  Recursing
        # on marginal grazing edges piles up spurious sub-path losses.
        if v_max <= 0.0:
            return loss
        edge = i0 + 1 + k
        return (loss
                + recurse(i0, edge, budget - 1)
                + recurse(edge, i1, budget - 1))

    return recurse(0, len(d) - 1, max_edges)
