"""Phase 2 physics: foliage/rain/gas models, bandwidth-derived sensitivity,
MIMO gain, deep-pit topography handling, and the new private-network presets."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.rf.environment import (foliage_loss_db,
                                         gaseous_attenuation_db_per_km,
                                         rain_loss_db,
                                         rain_specific_attenuation,
                                         thermal_sensitivity_dbm)
from app.services.rf.models import deygout_loss_db
from app.services.rf.physics import apply_earth_curvature
from app.services.rf.technologies import (TECHNOLOGIES, effective_sensitivity_dbm,
                                          get_technology, link_budget)
from app.services.terrain.fusion import TerrainFusionService


# --------------------------------------------------------------- vegetation
def test_weissberger_foliage():
    assert foliage_loss_db(900.0, 0.0) == 0.0
    # Short path (<=14 m) linear regime: 0.45 * 0.9^0.284 * 10 ~= 4.4 dB
    short = foliage_loss_db(900.0, 10.0)
    assert short == pytest.approx(0.45 * 0.9 ** 0.284 * 10, abs=0.01)
    # Deep foliage saturating-exponent regime, monotone in depth and freq.
    assert foliage_loss_db(900.0, 100.0) > foliage_loss_db(900.0, 30.0)
    assert foliage_loss_db(5800.0, 100.0) > foliage_loss_db(900.0, 100.0)
    # Validity clamp at 400 m.
    assert foliage_loss_db(900.0, 1000.0) == foliage_loss_db(900.0, 400.0)


# --------------------------------------------------------------------- rain
def test_p838_rain_coefficients():
    # Reference sanity: at 20 GHz, R=25 mm/h -> gamma ~= 0.0916*25^1.0568 ~ 2.75 dB/km
    g = rain_specific_attenuation(20_000.0, 25.0)
    assert g == pytest.approx(2.75, rel=0.1)
    # Negligible at UHF, brutal at mmWave.
    assert rain_specific_attenuation(900.0, 25.0) < 0.01
    assert rain_specific_attenuation(28_000.0, 25.0) > 4.0


def test_rain_effective_path():
    # Effective path < geometric path: 30 km at heavy rain is not 30 km of cell.
    full = rain_specific_attenuation(18_000.0, 40.0) * 30.0
    eff = rain_loss_db(18_000.0, 30_000.0, 40.0)
    assert 0 < eff < full


def test_gaseous_absorption():
    # Negligible at 1 GHz, noticeable at 23 GHz (water line), huge at 60 GHz.
    assert gaseous_attenuation_db_per_km(1000.0) < 0.02
    assert 0.1 < gaseous_attenuation_db_per_km(23_000.0) < 0.5
    assert gaseous_attenuation_db_per_km(60_000.0) > 10.0


# -------------------------------------------- sensitivity / MIMO / presets
def test_thermal_sensitivity_scaling():
    s10 = thermal_sensitivity_dbm(10.0, 7.0, -3.0)
    s100 = thermal_sensitivity_dbm(100.0, 7.0, -3.0)
    assert s100 - s10 == pytest.approx(10.0, abs=0.01)   # 10x BW = +10 dB
    # LTE 10 MHz, NF 7, SINR -3: -174+70+7-3 = -100 dBm
    assert s10 == pytest.approx(-100.0, abs=0.1)


def test_private_presets_and_mimo_budget():
    for key in ("private_lte_b48", "private_nr_n77", "private_lte_iot", "vhf150"):
        assert key in TECHNOLOGIES
    nr = get_technology("private_nr_n77")
    assert effective_sensitivity_dbm(nr) == pytest.approx(
        thermal_sensitivity_dbm(100.0, 7.0, -3.0), abs=0.01)
    b = link_budget(nr, path_loss_db_value=120.0)
    b_no = link_budget({**nr, "mimo_gain_db": 0.0}, path_loss_db_value=120.0)
    assert b["rx_power_dbm"] - b_no["rx_power_dbm"] == pytest.approx(6.0)
    # NB-IoT narrowband sensitivity beats the 100 MHz carrier by ~18.5 dB.
    iot = get_technology("private_lte_iot")
    assert effective_sensitivity_dbm(nr) - effective_sensitivity_dbm(iot) > 15.0


# ------------------------------------------------- deep-pit topography
def test_deep_pit_diffraction():
    """Open-pit mine scenario: RX at the bottom of a 150 m sheer-walled pit.
    The rim must act as a knife edge with heavy loss; a same-distance RX on
    flat ground must see ~0 diffraction."""
    d = np.linspace(0, 4000, 401)
    flat = np.full_like(d, 500.0)
    pit = flat.copy()
    pit[300:] = 350.0                       # sharp 150 m drop at 3 km (rim at idx 299)
    curved_flat = apply_earth_curvature(d, flat)
    curved_pit = apply_earth_curvature(d, pit)
    loss_flat = deygout_loss_db(d, curved_flat, 20, 1.5, 3600)
    loss_pit = deygout_loss_db(d, curved_pit, 20, 1.5, 3600)
    assert loss_flat < 2.0
    assert loss_pit > 15.0                  # rim shadows the pit floor hard


# --------------------------------------------------------------- API layer
@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


def test_profile_study_environment_breakdown(client):
    resp = client.get("/api/terrain/profile", params={
        "lat1": 47.0, "lon1": 14.9, "lat2": 47.0, "lon2": 15.1,
        "samples": 64, "technology": "ptp18000",
        "rain_rate_mm_h": 40, "foliage_depth_m": 20})
    assert resp.status_code == 200, resp.text
    s = resp.json()["study"]
    assert s["rain_loss_db"] > 5.0          # 18 GHz in 40 mm/h rain hurts
    assert s["gaseous_loss_db"] > 0.5       # ~15 km of air at 18 GHz
    assert s["foliage_loss_db"] > 10.0
    assert "sensitivity_dbm" in s
    # The same path without weather has a strictly better margin.
    dry = client.get("/api/terrain/profile", params={
        "lat1": 47.0, "lon1": 14.9, "lat2": 47.0, "lon2": 15.1,
        "samples": 64, "technology": "ptp18000"}).json()["study"]
    assert dry["margin_db"] > s["margin_db"] + 5.0


def test_coverage_with_foliage_shrinks(client):
    base = {"lat": 47.0, "lon": 15.0, "technology": "private_nr_n77",
            "radius_km": 12, "n_radials": 36, "n_steps": 40}
    clear = client.post("/api/rf/coverage", json=base).json()
    wooded = client.post("/api/rf/coverage",
                         json={**base, "foliage_depth_m": 60}).json()
    assert wooded["stats"]["served_area_fraction"] \
        < clear["stats"]["served_area_fraction"]
