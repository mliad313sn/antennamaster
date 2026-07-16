#!/usr/bin/env python3
"""Precision benchmark: prediction vs reference / measurement, regenerated in CI.

    python -m tools.validate_predictions          # writes PRECISION_BENCHMARK.md

Two sections, deliberately distinct:

A. IMPLEMENTATION EXACTNESS — the NTIA ITM engine is run against the published
   Crystal Palace reference case and the *actual deviation in dB* is reported
   for all six published quantile combinations. This proves the algorithm is
   exact; it is recomputed (never hardcoded) on every run.

B. FIELD ACCURACY — every measurement dataset found in
   ``backend/benchmarks/measurements/*.json`` is replayed through the
   prediction engine and scored (RMSE / mean bias / std per environment).
   Datasets are real drive/walk-test campaigns dropped in by operators —
   this repository ships NONE fabricated: if the folder is empty the report
   says so instead of inventing numbers.

Dataset format (one JSON per campaign)::

    {"name": "...", "environment": "urban|suburban|rural",
     "tx": {"lat":.., "lon":.., "h_m":.., "freq_mhz":..,
            "tx_power_dbm":.., "tx_gain_dbi":.., "losses_db":..},
     "rx_height_m": 1.5, "model": "okumura_hata",
     "rmse_target_db": 8.0,
     "points": [{"lat":.., "lon":.., "rssi_dbm":..}, ...]}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
MEASUREMENTS = ROOT / "benchmarks" / "measurements"
REPORT = ROOT.parent / "PRECISION_BENCHMARK.md"


# ------------------------------------------------- A. implementation exactness
def itm_exactness() -> list[dict]:
    from app.services.rf.itm_exact import itm_p2p_loss
    from tests.test_itm_exact import CRYSTAL_PALACE_PROFILE, DIST_M, EXPECTED

    d = np.linspace(0.0, DIST_M, len(CRYSTAL_PALACE_PROFILE))
    rows = []
    for (conf, rel), expected in sorted(EXPECTED.items()):
        got = itm_p2p_loss(d, CRYSTAL_PALACE_PROFILE, 143.9, 8.5, 41.5,
                           reliability_pct=rel, confidence_pct=conf,
                           eps=15, sgm=0.005, en0=314, climate=5,
                           polarization=0)["path_loss_db"]
        rows.append({"confidence_pct": conf, "reliability_pct": rel,
                     "expected_db": expected, "computed_db": round(got, 4),
                     "deviation_db": round(abs(got - expected), 4)})
    return rows


# ------------------------------------------- A2. ITU reference validation
VALIDATION = ROOT / "benchmarks" / "validation"


def p452_validation() -> dict | None:
    """Replay the official ITU-R P.452-18 validation example through the
    installed reference engine; return the worst deviation."""
    try:
        from Py452 import P452
    except Exception:
        return None
    import csv
    prof_rows = list(csv.reader(
        (VALIDATION / "p452_profile.csv").open()))[1:]
    d = np.array([float(r[0]) for r in prof_rows])
    h = np.array([float(r[1]) for r in prof_rows])
    cover = np.array([float(r[2]) for r in prof_rows])
    zone = np.array([int(r[4]) for r in prof_rows])
    g = h + cover
    worst, n = 0.0, 0
    with (VALIDATION / "p452_results.csv").open() as f:
        for row in csv.DictReader(f):
            lb = P452.bt_loss(
                float(row["f (GHz)"]), float(row["p (%)"]), d, h, g, zone,
                float(row["htg (m)"]), float(row["hrg (m)"]),
                float(row["phit_e (deg)"]), float(row["phit_n (deg)"]),
                float(row["phir_e (deg)"]), float(row["phir_n (deg)"]),
                float(row["Gt (dBi)"]), float(row["Gr (dBi)"]),
                int(row["pol (1-h/2-v)"]),
                float(row["dct (km)"]), float(row["dcr (km)"]),
                float(row["press (hPa)"]), float(row["temp (deg C)"]))
            worst = max(worst, abs(float(np.atleast_1d(lb)[0])
                                   - float(row["Lb"])))
            n += 1
    return {"recommendation": "ITU-R P.452-18",
            "cases": n, "worst_deviation_db": worst}


def p2001_validation() -> dict | None:
    """Replay the official ITU-R P.2001 validation example subset through the
    installed reference engine; return the worst deviation."""
    try:
        from Py2001 import P2001
    except Exception:
        return None
    import pandas as pd
    prof = pd.read_csv(VALIDATION / "p2001_profile.csv", skiprows=9,
                       names=["d", "h", "z"])
    res = pd.read_csv(VALIDATION / "p2001_results.csv")
    worst = 0.0
    for _, row in res.iterrows():
        lb = P2001.bt_loss(prof.d.to_numpy(), prof.h.to_numpy(),
                           prof.z.to_numpy(), row.GHz, row.Tpc,
                           row.Phire, row.Phirn, row.Phite, row.Phitn,
                           row.Hrg, row.Htg, row.Grx, row.Gtx,
                           int(row.FlagVp))
        worst = max(worst, abs(float(np.atleast_1d(lb)[0]) - float(row.Lb)))
    return {"recommendation": "ITU-R P.2001",
            "cases": len(res), "worst_deviation_db": worst}


# ----------------------------------------------------- B. field accuracy
def replay_dataset(ds: dict) -> dict:
    from app.services.rf.calibration import calibrate_model
    from app.services.rf.planning import evaluate_receiver
    from app.services.terrain.fusion import TerrainFusionService

    if ds.get("terrain") == "ramp":
        # Synthetic pipeline-proof datasets replay on the deterministic ramp
        # DEM they were generated against — network-free and reproducible.
        import tempfile

        from tools._ramp_terrain import RampTileStore
        fusion = TerrainFusionService(
            store=RampTileStore(Path(tempfile.mkdtemp(prefix="ramp-dem-"))))
    else:
        fusion = TerrainFusionService()
    tx = ds["tx"]
    tech = {
        "freq_mhz": float(tx["freq_mhz"]), "model": ds.get("model", "okumura_hata"),
        "environment": ds.get("environment", "urban"),
        "tx_power_dbm": float(tx["tx_power_dbm"]),
        "tx_gain_dbi": float(tx.get("tx_gain_dbi", 0.0)),
        "rx_gain_dbi": 0.0, "losses_db": float(tx.get("losses_db", 0.0)),
        "rx_sensitivity_dbm": -120.0,
        "h_bs_m": float(tx["h_m"]), "h_ut_m": float(ds.get("rx_height_m", 1.5)),
    }
    pred, meas, dist = [], [], []
    for p in ds["points"]:
        r = evaluate_receiver(fusion, dict(tech), tx["lat"], tx["lon"],
                              float(p["lat"]), float(p["lon"]))
        pred.append(r["rx_power_dbm"]); meas.append(float(p["rssi_dbm"]))
        dist.append(r["distance_m"])
    pred_a, meas_a = np.array(pred), np.array(meas)
    err = meas_a - pred_a
    fit = calibrate_model(pred, meas, dist)
    return {
        "name": ds["name"], "environment": ds.get("environment", "?"),
        "model": tech["model"], "n_points": len(pred),
        "rmse_db": round(float(np.sqrt(np.mean(err ** 2))), 2),
        "bias_db": round(float(err.mean()), 2),
        "std_db": round(float(err.std()), 2),
        "rmse_after_calibration_db": fit["rms_error_offset_slope_db"],
        "rmse_target_db": ds.get("rmse_target_db"),
        "synthetic": bool(ds.get("synthetic", False)),
    }


def field_accuracy() -> list[dict]:
    out = []
    if MEASUREMENTS.exists():
        for path in sorted(MEASUREMENTS.glob("*.json")):
            try:
                out.append(replay_dataset(json.loads(path.read_text())))
            except Exception as exc:  # a bad dataset must not kill the report
                out.append({"name": path.name, "error": str(exc)[:200]})
    return out


# ------------------------------------------------------------------ report
def build_report() -> str:
    exact = itm_exactness()
    field = field_accuracy()
    worst = max(r["deviation_db"] for r in exact)

    lines = [
        "# AntennaMaster — Precision Benchmark",
        "",
        "Regenerated by `python -m tools.validate_predictions` (run in CI).",
        "Nothing in this report is hardcoded: every number is recomputed.",
        "",
        "## A. Implementation exactness — NTIA ITM vs published reference",
        "",
        "Published point-to-point validation case: Crystal Palace (UK), 77.8 km,",
        "41.5 MHz, TX 143.9 m / RX 8.5 m, horizontal polarization.",
        "",
        "| Confidence % | Reliability % | Expected dB | Computed dB | Deviation dB |",
        "|---|---|---|---|---|",
    ]
    for r in exact:
        lines.append(f"| {r['confidence_pct']} | {r['reliability_pct']} | "
                     f"{r['expected_db']} | {r['computed_db']} | "
                     f"{r['deviation_db']} |")
    lines += [
        "",
        f"**Worst deviation: {worst} dB** (gate: ≤ 0.1 dB).",
        "",
        "The ITU-R P.1812 engine is the official ITU-R SG3 reference code",
        "(Py1812 v6) with the ITU digital maps installed from itu.int.",
        "",
        "### Official ITU validation examples (P.452-18 and P.2001)",
        "",
        "The interference (P.452-18) and wide-range (P.2001) engines are the",
        "official reference implementations; this installation replays the",
        "ITU-R software-validation examples shipped with them",
        "(`benchmarks/validation/`) on every run:",
        "",
        "| Recommendation | Validation cases | Worst deviation | Gate |",
        "|---|---|---|---|",
    ]
    for v in (p452_validation(), p2001_validation()):
        if v is None:
            lines.append("| (engine not installed) | — | — | — |")
        else:
            lines.append(f"| {v['recommendation']} | {v['cases']} | "
                         f"{v['worst_deviation_db']:.2e} dB | ≤ 1e-06 dB |")
    lines += [
        "",
        "## B. Field accuracy — prediction vs measured drive tests",
        "",
    ]
    if not field:
        lines += [
            "*No measurement datasets present yet.* This section refuses to",
            "invent numbers: drop real campaign files into",
            "`backend/benchmarks/measurements/*.json` (format in",
            "`tools/validate_predictions.py`) and re-run — RMSE / bias / std",
            "per environment will appear here, gated in CI against each",
            "dataset's `rmse_target_db` (targets: ≤ 8 dB urban, ≤ 6 dB rural).",
        ]
    else:
        lines += ["| Dataset | Env | Model | N | RMSE dB | Bias dB | Std dB | RMSE after cal. | Target |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in field:
            if "error" in r:
                lines.append(f"| {r['name']} | — | — | — | ERROR: {r['error']} | | | | |")
            else:
                tag = " *(synthetic)*" if r.get("synthetic") else ""
                lines.append(
                    f"| {r['name']}{tag} | {r['environment']} | {r['model']} | "
                    f"{r['n_points']} | {r['rmse_db']} | {r['bias_db']} | "
                    f"{r['std_db']} | {r['rmse_after_calibration_db']} | "
                    f"{r['rmse_target_db'] or '—'} |")
        if any(r.get("synthetic") for r in field if "error" not in r):
            lines += [
                "",
                "**Synthetic rows are pipeline proof, not field evidence.**",
                "They are the platform's own prediction over a deterministic",
                "synthetic terrain plus seeded log-normal shadowing (σ 6 dB",
                "urban / 4 dB rural), so a correct pipeline must land at",
                "RMSE ≈ σ — under the gates (≤ 8 dB urban, ≤ 6 dB rural).",
                "They prove the ingest → predict → fit → gate machinery is",
                "armed end-to-end. Real-world field accuracy remains",
                "**unproven** until real campaigns are ingested with",
                "`python -m tools.ingest_drive_test` (CSV or GPX).",
            ]
        if not any(not r.get("synthetic") for r in field if "error" not in r):
            lines += [
                "",
                "*No real (non-synthetic) measurement datasets present yet.*",
            ]
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = build_report()
    REPORT.write_text(report)
    print(report)
    print(f"\nwrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
