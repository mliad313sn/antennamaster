"""Tests: the precision benchmark harness (C8) — CI gate for exactness."""
import json

import numpy as np
import pytest

from tools.validate_predictions import (MEASUREMENTS, build_report,
                                        field_accuracy, itm_exactness,
                                        replay_dataset)


def test_itm_exactness_gate():
    """The CI precision gate: every published quantile within 0.1 dB."""
    rows = itm_exactness()
    assert len(rows) == 6
    worst = max(r["deviation_db"] for r in rows)
    assert worst <= 0.1, f"ITM deviates {worst} dB from the published reference"


def test_report_builds_and_is_honest():
    report = build_report()
    assert "Implementation exactness" in report
    assert "Field accuracy" in report
    # With no measurement datasets shipped, the report must SAY so rather
    # than contain fabricated field numbers.
    if not list(MEASUREMENTS.glob("*.json")) if MEASUREMENTS.exists() else True:
        assert "No measurement datasets present" in report


def test_field_datasets_meet_their_targets(fake_store, monkeypatch):
    """Any real dataset dropped into benchmarks/measurements is CI-gated
    against its own rmse_target_db."""
    import app.services.terrain.fusion as fm
    monkeypatch.setattr(fm, "get_tile_store", lambda: fake_store)
    for row in field_accuracy():
        if "error" in row:
            pytest.fail(f"dataset {row['name']} failed to replay: {row['error']}")
        target = row.get("rmse_target_db")
        if target:
            assert row["rmse_db"] <= target, \
                f"{row['name']}: RMSE {row['rmse_db']} dB exceeds target {target}"


def test_replay_dataset_math(fake_store, monkeypatch):
    """Harness math check on a self-generated campaign: predictions replayed
    against themselves + known bias must report exactly that bias."""
    import app.services.terrain.fusion as fm
    monkeypatch.setattr(fm, "get_tile_store", lambda: fake_store)
    from app.services.rf.planning import evaluate_receiver
    from app.services.terrain.fusion import TerrainFusionService
    fusion = TerrainFusionService(store=fake_store)
    tech = {"freq_mhz": 900.0, "model": "okumura_hata", "environment": "urban",
            "tx_power_dbm": 43.0, "tx_gain_dbi": 15.0, "rx_gain_dbi": 0.0,
            "losses_db": 3.0, "rx_sensitivity_dbm": -120.0,
            "h_bs_m": 30.0, "h_ut_m": 1.5}
    pts = []
    for dlon in (0.02, 0.05, 0.09, 0.13):
        r = evaluate_receiver(fusion, dict(tech), 47.0, 15.0, 47.0, 15.0 + dlon)
        pts.append({"lat": 47.0, "lon": 15.0 + dlon,
                    "rssi_dbm": r["rx_power_dbm"] - 4.0})   # known -4 dB bias
    ds = {"name": "selftest", "environment": "urban", "model": "okumura_hata",
          "tx": {"lat": 47.0, "lon": 15.0, "h_m": 30.0, "freq_mhz": 900.0,
                 "tx_power_dbm": 43.0, "tx_gain_dbi": 15.0, "losses_db": 3.0},
          "rx_height_m": 1.5, "points": pts}
    row = replay_dataset(ds)
    assert row["bias_db"] == pytest.approx(-4.0, abs=0.1)
    assert row["rmse_db"] == pytest.approx(4.0, abs=0.1)
    assert row["rmse_after_calibration_db"] < 0.5     # pure offset calibrates out
