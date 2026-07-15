"""Drive-test / walk-test calibration.

Turns predictions into *trusted* predictions: ingest measured RSSI (CSV or
GPX) and least-squares fit an empirical correction to the model so predicted
matches reality.  The correction has two terms,

    corrected = predicted + offset + slope * log10(d_km)

an overall bias (offset) and a distance-dependent slope (captures a wrong
path-loss exponent).  Reports RMSE/MAE before and after so the improvement is
quantified, exactly like a commercial model-tuning (K-factor) workflow.
"""
from __future__ import annotations

import csv
import io

import numpy as np


# --------------------------------------------------------------------------- #
#  Ingestion
# --------------------------------------------------------------------------- #
def parse_csv(text: str) -> list[dict]:
    """Parse a drive-test CSV with lat, lon and an RSSI/measured column.

    Accepts common header spellings (lat/latitude, lon/lng/longitude,
    rssi/measured_dbm/rsrp/level_dbm).  Returns [{lat, lon, measured_dbm}].
    """
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    norm = {name.strip().lower(): name for name in reader.fieldnames}

    def pick(*cands):
        for c in cands:
            if c in norm:
                return norm[c]
        return None

    lat_c = pick("lat", "latitude", "y")
    lon_c = pick("lon", "lng", "long", "longitude", "x")
    val_c = pick("rssi", "measured_dbm", "rsrp", "rscp", "level_dbm",
                 "signal_dbm", "dbm", "level")
    if not (lat_c and lon_c and val_c):
        raise ValueError("CSV must have latitude, longitude and an RSSI/dBm "
                         "column (e.g. lat, lon, rssi).")
    rows = []
    for r in reader:
        try:
            rows.append({"lat": float(r[lat_c]), "lon": float(r[lon_c]),
                         "measured_dbm": float(r[val_c])})
        except (TypeError, ValueError):
            continue
    return rows


def parse_gpx(text: str) -> list[dict]:
    """Parse a GPX track; RSSI is read from a <measured>/<rssi>/<dbm> extension
    or the trackpoint <cmt>/<name> text if it is numeric."""
    try:
        import gpxpy
    except ImportError:  # pragma: no cover - gpxpy is a declared dependency
        return _parse_gpx_stdlib(text)
    gpx = gpxpy.parse(text)
    rows = []
    for track in gpx.tracks:
        for seg in track.segments:
            for pt in seg.points:
                val = None
                for src in (pt.comment, pt.name, pt.description):
                    if src is not None:
                        try:
                            val = float(str(src).strip())
                            break
                        except ValueError:
                            continue
                if val is not None:
                    rows.append({"lat": pt.latitude, "lon": pt.longitude,
                                 "measured_dbm": val})
    return rows


def _parse_gpx_stdlib(text: str) -> list[dict]:  # pragma: no cover - fallback
    import xml.etree.ElementTree as ET
    root = ET.fromstring(text)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    rows = []
    for pt in root.iter():
        if pt.tag.endswith("trkpt"):
            lat, lon = pt.get("lat"), pt.get("lon")
            val = None
            for child in pt:
                if child.tag.split("}")[-1] in ("cmt", "name", "desc") and child.text:
                    try:
                        val = float(child.text.strip())
                    except ValueError:
                        pass
            if lat and lon and val is not None:
                rows.append({"lat": float(lat), "lon": float(lon),
                             "measured_dbm": val})
    return rows


# --------------------------------------------------------------------------- #
#  Fitting
# --------------------------------------------------------------------------- #
def fit_correction(predicted_dbm, measured_dbm, distances_m=None) -> dict:
    """Least-squares fit of correction = offset + slope*log10(d_km).

    Without distances (or if degenerate) it fits a pure offset (mean bias).
    Returns the coefficients and RMSE/MAE before and after correction.
    """
    p = np.asarray(predicted_dbm, dtype=np.float64)
    m = np.asarray(measured_dbm, dtype=np.float64)
    n = p.size
    if n == 0:
        raise ValueError("No paired samples to calibrate.")
    resid = m - p                       # what the model is missing

    slope = 0.0
    offset = float(np.mean(resid))
    if distances_m is not None and n >= 2:
        d_km = np.maximum(np.asarray(distances_m, dtype=np.float64) / 1000.0, 1e-3)
        x = np.log10(d_km)
        if np.ptp(x) > 1e-6:            # distances vary -> can fit a slope
            A = np.column_stack([np.ones_like(x), x])
            coef, *_ = np.linalg.lstsq(A, resid, rcond=None)
            offset, slope = float(coef[0]), float(coef[1])
            corrected = p + offset + slope * x
        else:
            corrected = p + offset
    else:
        corrected = p + offset

    def rmse(a):
        return float(np.sqrt(np.mean((m - a) ** 2)))

    def mae(a):
        return float(np.mean(np.abs(m - a)))

    return {
        "n_samples": int(n),
        "offset_db": round(offset, 2),
        "slope_db_per_decade": round(slope, 2),
        "rmse_before_db": round(rmse(p), 2),
        "rmse_after_db": round(rmse(corrected), 2),
        "mae_before_db": round(mae(p), 2),
        "mae_after_db": round(mae(corrected), 2),
        "mean_bias_db": round(float(np.mean(resid)), 2),
    }
