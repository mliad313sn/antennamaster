"""Phase 5 tests: EMF (FCC/ICNIRP) exposure compliance, ITM propagation, and
drive-test calibration (CSV/GPX parsing + least-squares correction fit)."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.rf import calibration as cal
from app.services.rf import emf, itm
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


# ------------------------------------------------------ EMF compliance
def test_public_zone_stricter_than_occupational():
    z = emf.exposure_zones(900.0, 46.0, 17.0, mount_height_m=20.0)
    assert z["public"]["compliance_distance_m"] > z["occupational"]["compliance_distance_m"]
    assert z["mpe_public_wm2"] < z["mpe_occupational_wm2"]


def test_higher_power_larger_zone():
    lo = emf.exposure_zones(900.0, 30.0, 15.0)
    hi = emf.exposure_zones(900.0, 46.0, 15.0)
    assert hi["public"]["compliance_distance_m"] > lo["public"]["compliance_distance_m"]


def test_compliance_distance_formula():
    # S = EIRP*F/(4 pi r^2) -> r = sqrt(EIRP*F/(4 pi S)).
    eirp = emf.eirp_watts(43.0, 15.0)          # 58 dBm EIRP
    r = emf.compliance_distance_m(eirp, 10.0, reflection_factor=1.0)
    assert r == pytest.approx(np.sqrt(eirp / (4 * np.pi * 10.0)), rel=1e-6)


def test_fcc_vs_icnirp_both_supported():
    f = emf.exposure_zones(1800.0, 46.0, 18.0, standard="fcc")
    i = emf.exposure_zones(1800.0, 46.0, 18.0, standard="icnirp")
    assert f["standard"] == "fcc" and i["standard"] == "icnirp"
    assert f["public"]["compliance_distance_m"] > 0
    assert i["public"]["compliance_distance_m"] > 0


def test_emf_endpoint(client):
    r = client.post("/api/rf/emf-compliance", json={
        "technology": "lte800", "mount_height_m": 25.0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "occupational" in body and "public" in body


# ------------------------------------------------------ ITM
def _profile(dh=0.0):
    d = np.linspace(0, 20_000, 201)
    e = np.full_like(d, 100.0)
    if dh:
        rng = np.random.default_rng(1)
        e = e + rng.normal(0, dh, size=e.shape)
    return d, e


def test_interdecile_dh_rises_with_roughness():
    _, flat = _profile(0.0)
    _, rough = _profile(50.0)
    d, _ = _profile()
    assert itm.interdecile_dh(d, rough) > itm.interdecile_dh(d, flat)


def test_itm_loss_exceeds_free_space():
    d, e = _profile(0.0)
    res = itm.itm_point_to_point(d, e, 900.0, 30.0, 1.5)
    assert res["loss_db"] >= res["free_space_db"]
    assert res["regime"] in ("line_of_sight", "diffraction", "troposcatter")


def test_itm_regime_transitions_with_distance():
    # Short path -> LOS; very long path -> beyond horizon (diffraction/scatter).
    d_short = np.linspace(0, 2_000, 101)
    e_short = np.full_like(d_short, 100.0)
    d_long = np.linspace(0, 120_000, 401)
    e_long = np.full_like(d_long, 100.0)
    short = itm.itm_point_to_point(d_short, e_short, 900.0, 30.0, 1.5)
    long = itm.itm_point_to_point(d_long, e_long, 900.0, 30.0, 1.5)
    assert short["regime"] == "line_of_sight"
    assert long["regime"] in ("diffraction", "troposcatter")
    assert long["loss_db"] > short["loss_db"]


def test_itm_endpoint_compares_deygout(client):
    r = client.post("/api/rf/itm-profile", json={
        "lat1": 0.02, "lon1": 0.02, "lat2": 0.05, "lon2": 0.05,
        "freq_mhz": 900.0, "h_tx_m": 30.0, "h_rx_m": 1.5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "itm" in body and "deygout" in body and "difference_db" in body


# ------------------------------------------------------ calibration
def test_parse_csv_flexible_headers():
    text = "Latitude,Longitude,RSSI\n0.03,0.03,-85\n0.04,0.04,-92\n"
    rows = cal.parse_csv(text)
    assert len(rows) == 2
    assert rows[0]["measured_dbm"] == -85.0


def test_parse_csv_missing_column_raises():
    with pytest.raises(ValueError):
        cal.parse_csv("a,b\n1,2\n")


def test_fit_offset_only():
    pred = np.array([-80.0, -90.0, -100.0])
    meas = pred - 6.0                      # model is 6 dB optimistic
    fit = cal.fit_correction(pred, meas)
    assert fit["offset_db"] == pytest.approx(-6.0, abs=1e-6)
    assert fit["rmse_after_db"] < fit["rmse_before_db"]


def test_fit_offset_and_slope():
    d = np.array([100.0, 1000.0, 10000.0])
    pred = np.array([-70.0, -90.0, -110.0])
    # measured has an extra 5 dB/decade of distance loss the model missed.
    x = np.log10(d / 1000.0)
    meas = pred - 3.0 - 5.0 * x
    fit = cal.fit_correction(pred, meas, d)
    assert fit["slope_db_per_decade"] == pytest.approx(-5.0, abs=0.5)
    assert fit["rmse_after_db"] < 1.0


def test_fit_empty_raises():
    with pytest.raises(ValueError):
        cal.fit_correction([], [])


def test_calibrate_endpoint(client):
    r = client.post("/api/rf/calibrate", json={
        "tx_lat": 0.02, "tx_lon": 0.02, "technology": "lte800",
        "measurements": [
            {"lat": 0.03, "lon": 0.03, "measured_dbm": -85.0},
            {"lat": 0.05, "lon": 0.05, "measured_dbm": -100.0},
            {"lat": 0.07, "lon": 0.07, "measured_dbm": -110.0}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["calibration"]["n_samples"] == 3
    assert "rmse_after_db" in body["calibration"]


def test_calibrate_upload_csv(client):
    csv_bytes = (b"lat,lon,rssi\n0.03,0.03,-85\n0.05,0.05,-100\n0.07,0.07,-110\n")
    r = client.post("/api/rf/calibrate/upload?tx_lat=0.02&tx_lon=0.02&technology=lte800",
                    files={"file": ("drive.csv", csv_bytes, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["points_used"] == 3
