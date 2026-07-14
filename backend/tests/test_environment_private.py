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


# ------------------------------------------------- ITU-R P.2108 clutter
def test_p2108_clutter_reference_value():
    from app.services.rf.environment import clutter_loss_db
    # Hand-computed median at 2 GHz / 1 km:
    # Ll = 23.5 + 9.6 log10(2) = 26.39; Ls = 32.98 + 0 + 3 log10(2) = 33.88
    # Lctt = -5 log10(10^-5.278 + 10^-6.776) = 26.2 dB
    assert clutter_loss_db(2000.0, 1000.0, 50.0) == pytest.approx(26.2, abs=0.5)
    # Off switch and short-distance ramp.
    assert clutter_loss_db(2000.0, 1000.0, 0.0) == 0.0
    assert clutter_loss_db(2000.0, 50.0, 50.0) \
        < clutter_loss_db(2000.0, 500.0, 50.0)
    # Monotonic in location percentage and frequency.
    assert clutter_loss_db(2000.0, 1000.0, 90.0) \
        > clutter_loss_db(2000.0, 1000.0, 50.0) + 5.0
    assert clutter_loss_db(28000.0, 1000.0, 50.0) \
        > clutter_loss_db(2000.0, 1000.0, 50.0)
    # Vectorized over distance, saturating past 2 km.
    arr = clutter_loss_db(3500.0, np.array([500.0, 2000.0, 10_000.0]), 50.0)
    assert arr.shape == (3,)
    assert arr[1] == pytest.approx(arr[2], abs=1e-9)


def test_profile_and_coverage_with_clutter(client):
    params = {"lat1": 47.0, "lon1": 14.98, "lat2": 47.0, "lon2": 15.02,
              "samples": 64, "technology": "nr3500"}
    open_sky = client.get("/api/terrain/profile", params=params).json()
    cluttered = client.get("/api/terrain/profile",
                           params={**params, "clutter_pct": 90}).json()
    assert cluttered["study"]["clutter_loss_db"] > 20.0
    assert cluttered["study"]["margin_db"] \
        < open_sky["study"]["margin_db"] - 20.0
    # Sub-500 MHz callers get the conservative clamp warning.
    vhf = client.get("/api/terrain/profile", params={
        **params, "technology": "vhf150", "clutter_pct": 50}).json()
    assert any("P.2108" in w for w in vhf["study"]["warnings"])

    base = {"lat": 47.0, "lon": 15.0, "technology": "nr3500",
            "radius_km": 8, "n_radials": 36, "n_steps": 40}
    clear = client.post("/api/rf/coverage", json=base).json()
    urban = client.post("/api/rf/coverage",
                        json={**base, "clutter_pct": 75}).json()
    assert urban["stats"]["served_area_fraction"] \
        < clear["stats"]["served_area_fraction"]


# ------------------------------------------------- surface model (DSM)
def test_surface_model_not_configured_and_injected(client, fake_store,
                                                   monkeypatch):
    params = {"lat1": 47.0, "lon1": 14.99, "lat2": 47.0, "lon2": 15.01,
              "samples": 32, "surface": True}
    resp = client.get("/api/terrain/profile", params=params)
    assert resp.status_code == 422
    assert "AM_DSM_URL" in resp.json()["detail"]

    # Inject a "DSM" that sits 25 m above the fake DTM everywhere: the
    # surface profile must come back uniformly higher.
    class RaisedStore(type(fake_store)):
        def get_tile(self, z, x, y):
            return super().get_tile(z, x, y) + 25.0

    raised = RaisedStore(fake_store.cache_dir.parent)
    monkeypatch.setattr(routes_terrain, "_surface_fusion",
                        TerrainFusionService(store=raised))
    dtm = client.get("/api/terrain/profile",
                     params={**params, "surface": False}).json()
    dsm = client.get("/api/terrain/profile", params=params).json()
    assert dsm["surface"] is True
    diffs = [b["elev"] - a["elev"]
             for a, b in zip(dtm["points"], dsm["points"])]
    assert min(diffs) == pytest.approx(25.0, abs=0.01)
    assert max(diffs) == pytest.approx(25.0, abs=0.01)


def test_multisite_sinr_api(client):
    body = {"technology": "private_nr_n77", "radius_km": 6,
            "n_radials": 36, "n_steps": 30, "raster_px": 192,
            "sites": [{"lat": 47.0, "lon": 15.0},
                      {"lat": 47.0, "lon": 15.04}]}
    resp = client.post("/api/rf/coverage/multi", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["sinr"] is not None
    assert data["sinr"]["png_url"].endswith(".png")
    assert len(data["sinr"]["legend"]) == 5
    # n77 preset: 100 MHz / 7 dB NF -> noise floor = -87 dBm.
    assert data["sinr"]["noise_dbm"] == pytest.approx(-87.0, abs=0.5)
    png = client.get(data["sinr"]["png_url"])
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    # Interference analysis can be disabled.
    off = client.post("/api/rf/coverage/multi",
                      json={**body, "interference": False}).json()
    assert off["sinr"] is None
