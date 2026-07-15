#!/usr/bin/env python3
"""Ingest a real drive-test / walk-test survey (CSV or GPX) into a
benchmark measurement dataset.

    python -m tools.ingest_drive_test survey.csv \
        --name graz-lte800-urban --environment urban \
        --tx-lat 47.05 --tx-lon 15.42 --freq-mhz 806 --tx-power-dbm 43 \
        --h-tx-m 30 [--model okumura_hata] [--rmse-target-db 8]

Writes ``benchmarks/measurements/<name>.json`` in the format
``tools/validate_predictions.py`` replays, activating the CI RMSE gate for
that dataset (urban default target 8 dB, rural 6 dB).

Accepted inputs — only real measured values are ever written:

* **CSV** — columns are auto-detected case-insensitively:
  latitude (``lat|latitude|y``), longitude (``lon|lng|long|longitude|x``),
  RSSI (``rssi|rssi_dbm|level_dbm|rsrp|rsrp_dbm|signal|rx_power_dbm``).
* **GPX** — ``<trkpt>``/``<wpt>`` elements whose extensions (any namespace)
  or ``<desc>``/``<cmt>`` text carry a signal value, e.g.
  ``<gpxtpx:rssi>-87</gpxtpx:rssi>`` or ``desc="RSSI -87 dBm"``.

Rows without a plausible RSSI (must lie in [-150, -10] dBm) are dropped and
counted, never guessed.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEASUREMENTS = ROOT / "benchmarks" / "measurements"

LAT_COLS = ("lat", "latitude", "y")
LON_COLS = ("lon", "lng", "long", "longitude", "x")
RSSI_COLS = ("rssi", "rssi_dbm", "level", "level_dbm", "rsrp", "rsrp_dbm",
             "signal", "signal_dbm", "rx_power", "rx_power_dbm", "power_dbm")

# Environment → default CI gate (dB RMSE), per the platform's precision policy.
DEFAULT_TARGET = {"urban": 8.0, "rural": 6.0}


def _pick(cols: list[str], candidates: tuple[str, ...]) -> str | None:
    low = {c.lower().strip(): c for c in cols}
    for cand in candidates:
        if cand in low:
            return low[cand]
    return None


def _valid(lat: float, lon: float, rssi: float) -> bool:
    return (-90 <= lat <= 90 and -180 <= lon <= 180
            and -150 <= rssi <= -10)


def read_csv(path: Path) -> tuple[list[dict], int]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        rows = list(csv.DictReader(f, dialect=dialect))
    if not rows:
        raise SystemExit("CSV contains no data rows")
    cols = list(rows[0].keys())
    lat_c, lon_c = _pick(cols, LAT_COLS), _pick(cols, LON_COLS)
    rssi_c = _pick(cols, RSSI_COLS)
    if not (lat_c and lon_c and rssi_c):
        raise SystemExit(f"could not detect lat/lon/RSSI columns in {cols} — "
                         f"expected one of {LAT_COLS} / {LON_COLS} / {RSSI_COLS}")
    points, dropped = [], 0
    for r in rows:
        try:
            lat, lon = float(r[lat_c]), float(r[lon_c])
            rssi = float(re.sub(r"[^\d.\-]", "", r[rssi_c]))
        except (TypeError, ValueError):
            dropped += 1
            continue
        if _valid(lat, lon, rssi):
            points.append({"lat": lat, "lon": lon, "rssi_dbm": rssi})
        else:
            dropped += 1
    return points, dropped


_SIG_TAG = re.compile(r"(rssi|rsrp|signal|level)", re.I)
_SIG_TEXT = re.compile(r"(?:rssi|rsrp|signal|level)\D{0,8}(-\d+(?:\.\d+)?)",
                       re.I)


def _point_rssi(el: ET.Element) -> float | None:
    """Signal value from a trkpt/wpt: extension tag or desc/cmt text."""
    for child in el.iter():
        tag = child.tag.rsplit("}", 1)[-1]
        if _SIG_TAG.fullmatch(tag) and child.text:
            try:
                return float(child.text.strip())
            except ValueError:
                pass
    for child in el.iter():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag in ("desc", "cmt", "name") and child.text:
            m = _SIG_TEXT.search(child.text)
            if m:
                return float(m.group(1))
    return None


def read_gpx(path: Path) -> tuple[list[dict], int]:
    root = ET.parse(path).getroot()
    points, dropped = [], 0
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag not in ("trkpt", "wpt", "rtept"):
            continue
        try:
            lat, lon = float(el.get("lat")), float(el.get("lon"))
        except (TypeError, ValueError):
            dropped += 1
            continue
        rssi = _point_rssi(el)
        if rssi is not None and _valid(lat, lon, rssi):
            points.append({"lat": lat, "lon": lon, "rssi_dbm": rssi})
        else:
            dropped += 1
    return points, dropped


def build_dataset(points: list[dict], args) -> dict:
    target = args.rmse_target_db
    if target is None:
        target = DEFAULT_TARGET.get(args.environment)
    ds = {
        "name": args.name,
        "description": args.description or
            f"Drive-test survey ingested from {Path(args.input).name} "
            f"({len(points)} points).",
        "environment": args.environment,
        "model": args.model,
        "tx": {"lat": args.tx_lat, "lon": args.tx_lon,
               "freq_mhz": args.freq_mhz, "tx_power_dbm": args.tx_power_dbm,
               "tx_gain_dbi": args.tx_gain_dbi, "losses_db": args.losses_db,
               "h_m": args.h_tx_m},
        "rx_height_m": args.rx_height_m,
        "points": points,
    }
    if target is not None:
        ds["rmse_target_db"] = float(target)
    return ds


def main() -> int:
    ap = argparse.ArgumentParser(
        description="CSV/GPX drive-test → CI-gated measurement dataset")
    ap.add_argument("input", help=".csv or .gpx survey file")
    ap.add_argument("--name", required=True)
    ap.add_argument("--environment", default="urban",
                    choices=["urban", "suburban", "rural", "open"])
    ap.add_argument("--model", default="okumura_hata")
    ap.add_argument("--tx-lat", type=float, required=True)
    ap.add_argument("--tx-lon", type=float, required=True)
    ap.add_argument("--freq-mhz", type=float, required=True)
    ap.add_argument("--tx-power-dbm", type=float, required=True)
    ap.add_argument("--tx-gain-dbi", type=float, default=0.0)
    ap.add_argument("--losses-db", type=float, default=0.0)
    ap.add_argument("--h-tx-m", type=float, required=True)
    ap.add_argument("--rx-height-m", type=float, default=1.5)
    ap.add_argument("--rmse-target-db", type=float, default=None,
                    help="CI gate; defaults: urban 8, rural 6")
    ap.add_argument("--max-points", type=int, default=2000)
    ap.add_argument("--description", default=None)
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    src = Path(args.input)
    if src.suffix.lower() == ".csv":
        points, dropped = read_csv(src)
    elif src.suffix.lower() == ".gpx":
        points, dropped = read_gpx(src)
    else:
        raise SystemExit("input must be .csv or .gpx")
    if len(points) < 2:
        raise SystemExit(f"only {len(points)} usable points ({dropped} dropped)"
                         " — need at least 2")
    if len(points) > args.max_points:            # uniform decimation
        step = len(points) / args.max_points
        points = [points[int(i * step)] for i in range(args.max_points)]

    ds = build_dataset(points, args)
    out = Path(args.output) if args.output else MEASUREMENTS / f"{args.name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ds, indent=1) + "\n")
    print(f"wrote {out} — {len(points)} points kept, {dropped} dropped; "
          f"RMSE gate: {ds.get('rmse_target_db', 'none')} dB")
    print("run `python -m tools.validate_predictions` to refresh "
          "PRECISION_BENCHMARK.md; pytest gates it in CI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
