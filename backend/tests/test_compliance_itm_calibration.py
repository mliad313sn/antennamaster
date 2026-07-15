"""Tests: EMF exposure compliance, ITM (Longley-Rice), drive-test calibration."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.rf.calibration import (apply_correction, calibrate_drive_test,
                                         calibrate_model)
from app.services.rf.compliance import (assess_exposure, compliance_distance_m,
                                        fcc_mpe_w_m2, icnirp_limit_w_m2,
                                        power_density_w_m2)
from app.services.rf.itm import aknfe, itm_point_to_point, qerfi, terrain_dh_m
from app.services.rf.technologies import get_technology
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


# =============================================================== EMF compliance
def test_icnirp_and_fcc_limits_by_band():
    # ICNIRP public: 2 W/m^2 below 400 MHz, f/200 mid-band, 10 W/m^2 above 2 GHz.
    assert icnirp_limit_w_m2(150.0) == pytest.approx(2.0)
    assert icnirp_limit_w_m2(900.0) == pytest.approx(4.5)
    assert icnirp_limit_w_m2(3500.0) == pytest.approx(10.0)
    # Occupational limits are always >= public.
    assert icnirp_limit_w_m2(900.0, occupational=True) > icnirp_limit_w_m2(900.0)
    # FCC uncontrolled: 2 W/m^2 in 30-300 MHz, 10 W/m^2 above 1.5 GHz.
    assert fcc_mpe_w_m2(150.0) == pytest.approx(2.0)
    assert fcc_mpe_w_m2(2000.0) == pytest.approx(10.0)


def test_power_density_inverse_square_and_distance():
    # Doubling distance quarters the density.
    s1 = power_density_w_m2(50.0, 10.0)
    s2 = power_density_w_m2(50.0, 20.0)
    assert s2 == pytest.approx(s1 / 4.0, rel=1e-6)
    # Compliance distance inverts the density: at r_lim, S == limit.
    r = compliance_distance_m(50.0, 2.0)
    assert power_density_w_m2(50.0, r) == pytest.approx(2.0, rel=1e-6)


def test_assess_exposure_zones_and_verdict():
    res = assess_exposure(900.0, tx_power_dbm=43.0, antenna_gain_dbi=15.0,
                          standard="icnirp", assess_distance_m=5.0)
    assert res["public_compliance_distance_m"] > res["occupational_compliance_distance_m"]
    # Far away must be compliant; right at the antenna must not.
    near = assess_exposure(900.0, 43.0, 15.0, assess_distance_m=0.2)
    assert not near["public_compliant"]
    far = assess_exposure(900.0, 43.0, 15.0, assess_distance_m=50.0)
    assert far["public_compliant"]
    # Ground reflection raises the density (bigger exclusion zone).
    refl = assess_exposure(900.0, 43.0, 15.0, ground_reflection=True)
    assert refl["public_compliance_distance_m"] > res["public_compliance_distance_m"]


# ======================================================================= ITM
def test_itm_subfunctions_anchored():
    assert aknfe(0.0) == pytest.approx(6.02, abs=0.01)     # grazing knife edge
    assert qerfi(0.5) == pytest.approx(0.0, abs=1e-6)      # median deviate
    assert qerfi(0.1) > 0 and qerfi(0.9) < 0               # tails, correct sign


def test_terrain_dh_roughness():
    smooth = np.full(50, 100.0)
    assert terrain_dh_m(smooth) == pytest.approx(0.0, abs=1e-6)
    rough = 100.0 + 30.0 * np.sin(np.linspace(0, 6 * np.pi, 50))
    assert terrain_dh_m(rough) > 20.0


def test_itm_reduces_to_free_space_and_reliability_costs_margin():
    # Short, smooth, high-clearance LOS path -> total ~ free space + small.
    d = np.linspace(0, 2000, 101)
    flat = np.full_like(d, 100.0)
    med = itm_point_to_point(d, flat, 30.0, 30.0, 900.0,
                             reliability=0.5, confidence=0.5)
    assert med["regime"] == "line_of_sight"
    assert med["path_loss_db"] == pytest.approx(med["free_space_db"], abs=8.0)
    # 95% reliability must cost more loss than the median.
    hi = itm_point_to_point(d, flat, 30.0, 30.0, 900.0,
                            reliability=0.95, confidence=0.95)
    assert hi["path_loss_db"] > med["path_loss_db"]
    assert hi["variability_db"] > 0


def test_itm_obstruction_adds_diffraction():
    d = np.linspace(0, 10_000, 201)
    flat = np.full_like(d, 100.0)
    hill = flat + 120.0 * np.exp(-((d - 5000) / 300.0) ** 2)
    clear = itm_point_to_point(d, flat, 30.0, 30.0, 900.0)
    blocked = itm_point_to_point(d, hill, 30.0, 30.0, 900.0)
    assert blocked["diffraction_db"] > clear["diffraction_db"] + 5.0
    assert blocked["regime"] == "diffraction"


# =============================================================== calibration
def test_calibrate_offset_and_slope():
    rng = np.random.default_rng(0)
    dist = np.linspace(500, 20_000, 60)
    pred = -60 - 30 * np.log10(dist / 1000.0)
    # Measured = prediction with a +6 dB bias and a small slope error + noise.
    meas = pred + 6.0 - 2.0 * np.log10(dist / 1000.0) + rng.normal(0, 1.0, 60)
    fit = calibrate_model(pred, meas, dist)
    assert fit["rms_error_offset_db"] < fit["rms_error_before_db"]
    assert fit["rms_error_offset_slope_db"] <= fit["rms_error_offset_db"] + 0.1
    assert fit["offset_db"] == pytest.approx(4.0, abs=1.5)  # 6 - ~2 avg slope
    # Applying the correction pulls a fresh prediction toward measurement.
    corrected = apply_correction(-90.0, 5000.0, fit)
    assert corrected > -90.0     # positive bias raises the level
    with pytest.raises(ValueError):
        calibrate_model([1.0], [1.0], [1.0])


def test_calibrate_drive_test_end_to_end(fake_store):
    fusion = TerrainFusionService(store=fake_store)
    tech = get_technology("lte800")
    # Synthesize "measurements" from the model itself + a known 5 dB bias, so
    # the fitted offset must recover ~5 dB and the RMS must drop near zero.
    from app.services.rf.planning import evaluate_receiver
    pts = []
    for dlon in (0.02, 0.05, 0.08, 0.12, 0.18):
        r = evaluate_receiver(fusion, dict(tech), 47.0, 15.0, 47.0, 15.0 + dlon)
        pts.append({"lat": 47.0, "lon": 15.0 + dlon,
                    "rssi_dbm": r["rx_power_dbm"] + 5.0})
    out = calibrate_drive_test(fusion, tech, 47.0, 15.0, pts)
    assert out["fit"]["offset_db"] == pytest.approx(5.0, abs=0.5)
    assert out["fit"]["rms_error_offset_db"] < 1.0
    assert len(out["points"]) == 5


# ================================================================== API layer
def test_compliance_api(client):
    resp = client.post("/api/rf/compliance",
                       json={"freq_mhz": 900.0, "tx_power_dbm": 43.0,
                             "antenna_gain_dbi": 15.0, "standard": "fcc",
                             "assess_distance_m": 3.0})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "public_compliance_distance_m" in data
    assert isinstance(data["public_compliant"], bool)


def test_itm_api(client):
    resp = client.get("/api/terrain/itm",
                      params={"lat1": 47.0, "lon1": 15.0,
                              "lat2": 47.0, "lon2": 15.1,
                              "h_tx_m": 30.0, "h_rx_m": 10.0,
                              "freq_mhz": 900.0, "reliability": 0.9})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["reliability"] == 0.9
    assert "path_loss_db" in data and "terrain_dh_m" in data


def test_calibration_api(client):
    body = {"technology": "lte800", "tx_lat": 47.0, "tx_lon": 15.0,
            "points": [{"lat": 47.0, "lon": 15.03, "rssi_dbm": -85.0},
                       {"lat": 47.0, "lon": 15.06, "rssi_dbm": -95.0},
                       {"lat": 47.0, "lon": 15.10, "rssi_dbm": -103.0}]}
    resp = client.post("/api/rf/calibrate", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["fit"]["n_points"] == 3
    assert len(data["points"]) == 3
