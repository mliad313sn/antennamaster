"""Model calibration from measured data (drive test / walk test).

A prediction is only trusted once it has been checked against reality.  This
module imports measured RSSI (from a drive test, walk test or a fleet of
CPEs), compares it to the model's prediction at the same points, and fits a
correction so the model matches the site.  It reports the predicted-vs-measured
error before and after -- turning predictions into *calibrated* predictions and
enabling continuous improvement.

FIT
    Two nested corrections, both least-squares:

      * OFFSET only:  a constant bias (feeder/connector/antenna/clutter error)
        -- the mean residual.
      * OFFSET + SLOPE:  a + b*log10(d/d0) -- also absorbs a distance-exponent
        mismatch (the model's path-loss slope being too steep or too shallow
        for the real clutter), the classic single-slope tuning of an
        Okumura-Hata-family model.

    RMS error before and after quantifies the improvement; the fitted terms are
    the correction to apply to future studies on this site.
"""
from __future__ import annotations

import numpy as np

REF_DISTANCE_M = 1000.0


def calibrate_model(predicted_dbm, measured_dbm, distances_m) -> dict:
    """Fit offset and offset+slope corrections to measured-vs-predicted RSSI.

    All three inputs are equal-length sequences.  Returns the fitted terms, the
    RMS error before/after each correction and the residual std (a measure of
    the irreducible location variability / shadow fade at the site).
    """
    pred = np.asarray(predicted_dbm, dtype=np.float64)
    meas = np.asarray(measured_dbm, dtype=np.float64)
    dist = np.asarray(distances_m, dtype=np.float64)
    n = pred.size
    if n < 2 or not (pred.size == meas.size == dist.size):
        raise ValueError("need >=2 equal-length predicted/measured/distance series")

    residual = meas - pred
    rms_before = float(np.sqrt(np.mean(residual ** 2)))

    # Offset-only correction.
    offset = float(np.mean(residual))
    rms_offset = float(np.sqrt(np.mean((residual - offset) ** 2)))

    # Offset + slope: residual ~ a + b*log10(d/d0).
    logd = np.log10(np.maximum(dist, 1.0) / REF_DISTANCE_M)
    A = np.column_stack([np.ones_like(logd), logd])
    (a, b), *_ = np.linalg.lstsq(A, residual, rcond=None)
    fit = A @ np.array([a, b])
    rms_slope = float(np.sqrt(np.mean((residual - fit) ** 2)))

    return {
        "n_points": int(n),
        "rms_error_before_db": round(rms_before, 2),
        "offset_db": round(offset, 2),
        "rms_error_offset_db": round(rms_offset, 2),
        "slope_intercept_db": round(float(a), 2),
        "slope_per_decade_db": round(float(b), 2),
        "rms_error_offset_slope_db": round(rms_slope, 2),
        "residual_std_db": round(float(np.std(residual - fit)), 2),
        "mean_measured_dbm": round(float(np.mean(meas)), 1),
        "mean_predicted_dbm": round(float(np.mean(pred)), 1),
        "recommended": "offset_slope" if rms_slope < rms_offset - 0.5
        else "offset",
    }


def apply_correction(predicted_dbm: float, distance_m: float,
                     fit: dict, mode: str | None = None) -> float:
    """Apply a fitted correction to a fresh prediction."""
    mode = mode or fit.get("recommended", "offset")
    if mode == "offset_slope":
        logd = np.log10(max(distance_m, 1.0) / REF_DISTANCE_M)
        return predicted_dbm + fit["slope_intercept_db"] \
            + fit["slope_per_decade_db"] * logd
    return predicted_dbm + fit["offset_db"]


def correction_db(distances_m, fit: dict, mode: str | None = None):
    """Vectorized fitted correction (dB to ADD to predictions) — the hook the
    coverage engine uses to run site-tuned studies after a drive-test fit."""
    d = np.asarray(distances_m, dtype=np.float64)
    mode = mode or fit.get("recommended", "offset")
    if mode == "offset_slope":
        logd = np.log10(np.maximum(d, 1.0) / REF_DISTANCE_M)
        return (float(fit.get("slope_intercept_db", 0.0))
                + float(fit.get("slope_per_decade_db", 0.0)) * logd)
    return np.full(d.shape, float(fit.get("offset_db", 0.0)))


def calibrate_drive_test(fusion, tech: dict, tx_lat: float, tx_lon: float,
                         points: list[dict], k: float = 4.0 / 3.0,
                         grid=None, georef=None) -> dict:
    """Predict RSSI at each measured point, fit the correction and return the
    fit plus a per-point predicted/measured/error table.

    ``points`` is a list of ``{"lat","lon","rssi_dbm"}`` measurements.
    """
    from .planning import evaluate_receiver
    pred, meas, dist, rows = [], [], [], []
    for i, p in enumerate(points):
        res = evaluate_receiver(fusion, dict(tech), tx_lat, tx_lon,
                                float(p["lat"]), float(p["lon"]),
                                k=k, grid=grid, georef=georef)
        pr = res["rx_power_dbm"]
        ms = float(p["rssi_dbm"])
        pred.append(pr); meas.append(ms); dist.append(res["distance_m"])
        rows.append({"lat": p["lat"], "lon": p["lon"],
                     "distance_m": res["distance_m"],
                     "predicted_dbm": pr, "measured_dbm": round(ms, 1),
                     "error_db": round(ms - pr, 1)})
    fit = calibrate_model(pred, meas, dist)
    return {"fit": fit, "points": rows}
