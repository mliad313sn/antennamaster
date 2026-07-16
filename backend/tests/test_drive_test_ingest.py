"""Tests: CSV/GPX drive-test ingestion + the activated RMSE CI gates (P3)."""
import json
from argparse import Namespace
from pathlib import Path

import pytest

from tools.ingest_drive_test import build_dataset, read_csv, read_gpx

CSV_BODY = """Latitude;Longitude;RSRP_dBm;speed
47.05;15.42;-87.2;33
47.06;15.43;-91.0;35
47.07;15.44;bad;12
47.08;15.45;-300;9
47.09;15.46;-101.5;28
"""

GPX_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:x="http://example.com/sig/v1">
  <trk><trkseg>
    <trkpt lat="47.05" lon="15.42"><ele>360</ele>
      <extensions><x:rssi>-88</x:rssi></extensions></trkpt>
    <trkpt lat="47.06" lon="15.43">
      <desc>drive point, RSSI -93 dBm</desc></trkpt>
    <trkpt lat="47.07" lon="15.44"><ele>371</ele></trkpt>
  </trkseg></trk>
  <wpt lat="47.08" lon="15.45"><extensions><x:rsrp>-104.5</x:rsrp></extensions></wpt>
</gpx>
"""


def test_csv_autodetects_columns_and_drops_bad_rows(tmp_path):
    p = tmp_path / "survey.csv"
    p.write_text(CSV_BODY)
    points, dropped = read_csv(p)
    assert [pt["rssi_dbm"] for pt in points] == [-87.2, -91.0, -101.5]
    assert dropped == 2                       # 'bad' and the -300 outlier
    assert points[0] == {"lat": 47.05, "lon": 15.42, "rssi_dbm": -87.2}


def test_gpx_reads_extensions_and_desc_text(tmp_path):
    p = tmp_path / "survey.gpx"
    p.write_text(GPX_BODY)
    points, dropped = read_gpx(p)
    assert [pt["rssi_dbm"] for pt in points] == [-88.0, -93.0, -104.5]
    assert dropped == 1                       # trkpt without any signal value


def test_dataset_carries_environment_default_gate(tmp_path):
    args = Namespace(input="s.csv", name="x", environment="rural",
                     model="okumura_hata", tx_lat=47.0, tx_lon=15.0,
                     freq_mhz=806.0, tx_power_dbm=43.0, tx_gain_dbi=0.0,
                     losses_db=0.0, h_tx_m=30.0, rx_height_m=1.5,
                     rmse_target_db=None, description=None)
    ds = build_dataset([{"lat": 47, "lon": 15, "rssi_dbm": -90.0}], args)
    assert ds["rmse_target_db"] == 6.0        # rural default gate
    args.environment = "urban"
    assert build_dataset([], args)["rmse_target_db"] == 8.0
    args.rmse_target_db = 5.0                 # explicit target wins
    assert build_dataset([], args)["rmse_target_db"] == 5.0


# ------------------------------------------------------- activated CI gates
def _measurement_files():
    d = Path(__file__).resolve().parent.parent / "benchmarks" / "measurements"
    return sorted(d.glob("*.json")) if d.exists() else []


def test_pipeline_proof_datasets_exist_and_are_labelled():
    """The RMSE gates must be ARMED: at least the two synthetic
    pipeline-proof datasets ship, honestly labelled as synthetic."""
    names = {json.loads(p.read_text())["name"]: json.loads(p.read_text())
             for p in _measurement_files()}
    for want in ("synthetic-urban-pipelineproof", "synthetic-rural-pipelineproof"):
        assert want in names, f"{want} missing — gates are not armed"
        ds = names[want]
        assert ds["synthetic"] is True
        assert "NOT field evidence" in ds["description"]
        assert ds["terrain"] == "ramp"        # replays offline


def test_rmse_gates_hold_on_replay():
    """End-to-end: replay every shipped dataset through the real engine and
    enforce its rmse_target_db — the drive-test CI gate itself.  Synthetic
    ramp-terrain datasets replay network-free; real datasets (when present)
    replay on production terrain."""
    from tools.validate_predictions import replay_dataset
    rows = []
    for p in _measurement_files():
        ds = json.loads(p.read_text())
        if ds.get("terrain") != "ramp":
            continue                          # network datasets: gated in
                                              # test_precision_benchmark
        rows.append(replay_dataset(ds))
    assert rows, "no ramp-terrain datasets found"
    for r in rows:
        assert r["rmse_db"] <= r["rmse_target_db"], \
            f"{r['name']}: RMSE {r['rmse_db']} exceeds gate {r['rmse_target_db']}"
        # The injected shadowing sigma must be recovered (pipeline is honest:
        # RMSE ~= sigma, not suspiciously near zero).
        assert r["rmse_db"] >= 2.0


def test_calibration_loop_closes_end_to_end(fake_store, monkeypatch):
    """Fit a drive-test correction, apply it to a fresh coverage study, and
    verify the study actually shifted by the fitted offset — the closed
    Atoll-style tuning loop, not just a reported fit."""
    import app.api.routes_terrain as routes_terrain
    import app.services.terrain.fusion as fusion_mod
    from app.main import app
    from app.services.terrain.fusion import TerrainFusionService
    from fastapi.testclient import TestClient
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    client = TestClient(app)

    # Synthetic drive test: the "field" reads exactly 6 dB hotter than the
    # model everywhere -> the fit must recover a +6 dB offset.
    tx = {"lat": 47.0, "lon": 15.0}
    pts = []
    for i in range(12):
        lat, lon = 47.0 + 0.004 * (i + 1), 15.0 + 0.003 * (i + 1)
        from app.services.rf.planning import evaluate_receiver
        from app.services.rf.technologies import get_technology
        tech = get_technology("lte1800")
        pred = evaluate_receiver(
            TerrainFusionService(store=fake_store), dict(tech),
            tx["lat"], tx["lon"], lat, lon)["rx_power_dbm"]
        pts.append({"lat": lat, "lon": lon, "rssi_dbm": pred + 6.0})

    cal = client.post("/api/rf/calibrate", json={
        "tx_lat": tx["lat"], "tx_lon": tx["lon"], "technology": "lte1800",
        "points": pts})
    assert cal.status_code == 200, cal.text
    body = cal.json()
    assert body["calibration"]["offset_db"] == pytest.approx(6.0, abs=0.1)
    assert body["fit"]["rms_error_offset_db"] < 0.1   # perfect synthetic fit

    # Apply to coverage: peak RX must rise by the fitted correction.
    base = {"lat": tx["lat"], "lon": tx["lon"], "technology": "lte1800",
            "radius_km": 3, "n_radials": 36, "n_steps": 24, "raster_px": 128}
    plain = client.post("/api/rf/coverage", json=base).json()
    tuned = client.post("/api/rf/coverage", json={
        **base, "calibration": body["calibration"]}).json()
    dpeak = (tuned["stats"]["max_rx_power_dbm"]
             - plain["stats"]["max_rx_power_dbm"])
    assert dpeak == pytest.approx(6.0, abs=0.2), dpeak
    assert (tuned["stats"]["served_area_fraction"]
            >= plain["stats"]["served_area_fraction"])
