"""Phase 1 tests: bidirectional talk-back link balance, TIA-4046 DAQ grading
and repeater-system design (isolation, stability, cascade spacing)."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.rf import talkback
from app.services.rf.technologies import get_technology
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


@pytest.fixture
def fusion(fake_store):
    return TerrainFusionService(store=fake_store)


# --------------------------------------------------------------- DAQ ladder
def test_daq_monotonic_in_margin():
    """Higher margin never yields a lower DAQ grade."""
    margins = np.linspace(-20, 30, 51)
    daqs = [talkback.daq_from_margin(m)["daq"] for m in margins]
    assert daqs == sorted(daqs)


def test_daq_public_safety_threshold():
    # 5 dB above reference sensitivity is the DAQ 3.4 public-safety minimum.
    assert talkback.daq_from_margin(5.0)["daq"] == 3.4
    assert talkback.daq_from_margin(4.9)["daq"] == 3.0
    assert talkback.daq_from_margin(25.0)["daq"] == 5.0
    assert talkback.daq_from_margin(-50.0)["daq"] == 1.0


# --------------------------------------------------- portable profiles
def test_portable_profile_overrides():
    p = talkback.get_portable_profile("portable_handheld_5w",
                                      {"body_loss_db": 9.0, "tx_power_dbm": None})
    assert p["body_loss_db"] == 9.0
    assert p["tx_power_dbm"] == 37.0  # None override ignored


def test_portable_penetration_stacks_indoors():
    p = talkback.get_portable_profile("portable_indoor_5w")
    on_street = talkback._portable_penetration_db(p, "on_street")
    indoor = talkback._portable_penetration_db(p, "in_building")
    assert indoor == pytest.approx(on_street + p["building_penetration_db"])


def test_unknown_profile_raises():
    with pytest.raises(ValueError):
        talkback.get_portable_profile("nope")


# --------------------------------------------- bidirectional link balance
def test_bidirectional_uplink_is_the_limit(fusion):
    """A 46 dBm base into a 37 dBm portable: talk-in (uplink) is weaker, so it
    must be the limiting direction and combined DAQ = min of the two."""
    tech = get_technology("tetra400")
    portable = talkback.get_portable_profile("portable_handheld_5w")
    res = talkback.bidirectional_link(
        fusion, tech, portable, 0.02, 0.02, 0.05, 0.05)
    assert res.talk_in["margin_db"] <= res.talk_out["margin_db"]
    assert res.limiting_direction == "talk_in"
    assert res.combined["daq"] == min(res.talk_out["daq"], res.talk_in["daq"])
    # Path loss is reciprocal — one value drives both budgets.
    assert res.path_loss_db > 0


def test_reciprocal_pathloss_symmetry(fusion):
    """Swapping which asymmetry we test: raising ONLY portable TX power lifts
    talk-in but never talk-out (reciprocal path, asymmetric budgets)."""
    tech = get_technology("tetra400")
    weak = talkback.get_portable_profile("portable_handheld_5w",
                                         {"tx_power_dbm": 27.0})
    strong = talkback.get_portable_profile("portable_handheld_5w",
                                           {"tx_power_dbm": 40.0})
    a = talkback.bidirectional_link(fusion, tech, weak, 0.02, 0.02, 0.05, 0.05)
    b = talkback.bidirectional_link(fusion, tech, strong, 0.02, 0.02, 0.05, 0.05)
    assert b.talk_in["margin_db"] > a.talk_in["margin_db"]
    assert b.talk_out["margin_db"] == pytest.approx(a.talk_out["margin_db"])


def test_indoor_use_reduces_both_directions(fusion):
    tech = get_technology("tetra400")
    p = talkback.get_portable_profile("portable_indoor_5w")
    street = talkback.bidirectional_link(fusion, tech, p, 0.02, 0.02, 0.04, 0.04,
                                         user_environment="on_street")
    indoor = talkback.bidirectional_link(fusion, tech, p, 0.02, 0.02, 0.04, 0.04,
                                         user_environment="in_building")
    assert indoor.talk_out["margin_db"] < street.talk_out["margin_db"]
    assert indoor.talk_in["margin_db"] < street.talk_in["margin_db"]


# --------------------------------------------------- repeater design
def test_antenna_isolation_increases_with_separation():
    close = talkback.antenna_isolation_db(400.0, 1.0, "vertical")
    far = talkback.antenna_isolation_db(400.0, 10.0, "vertical")
    assert far > close


def test_repeater_stability_gate():
    s = talkback.repeater_stability(system_gain_db=80.0, isolation_db=90.0,
                                    stability_margin_db=15.0)
    assert s["max_stable_gain_db"] == pytest.approx(75.0)
    assert s["stable"] is False       # 80 dB gain > 75 dB max
    s2 = talkback.repeater_stability(70.0, 90.0, 15.0)
    assert s2["stable"] is True
    assert s2["headroom_db"] == pytest.approx(5.0)


def test_cascade_spacing_overlap():
    c = talkback.cascade_spacing(5000.0, overlap_fraction=0.2)
    # 2 * 5000 * (1 - 0.2) = 8000 m
    assert c["spacing_m"] == pytest.approx(8000.0)


def test_repeater_design_bundles_cascade():
    d = talkback.repeater_design(450.0, 70.0, 5.0, reliable_range_m=3000.0)
    assert "cascade" in d and "isolation" in d
    assert d["isolation"]["stable"] in (True, False)


# --------------------------------------------------------------- API
def test_portable_profiles_endpoint(client):
    r = client.get("/api/rf/portable-profiles")
    assert r.status_code == 200
    body = r.json()
    assert any(p["key"] == "portable_handheld_5w" for p in body["profiles"])
    assert body["daq_ladder"][0]["daq"] == 5.0


def test_talkback_endpoint(client):
    r = client.post("/api/rf/talkback", json={
        "base_lat": 0.02, "base_lon": 0.02,
        "portable_lat": 0.05, "portable_lon": 0.05,
        "technology": "tetra400", "portable_profile": "portable_handheld_5w"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "talk_out" in body and "talk_in" in body and "combined" in body
    assert body["limiting_direction"] in ("talk_in", "talk_out")
    assert 1.0 <= body["combined"]["daq"] <= 5.0


def test_talkback_batch_endpoint(client):
    r = client.post("/api/rf/talkback/batch", json={
        "base_lat": 0.02, "base_lon": 0.02,
        "technology": "tetra400", "portable_profile": "portable_handheld_5w",
        "portables": [{"lat": 0.03, "lon": 0.03, "name": "A"},
                      {"lat": 0.08, "lon": 0.08, "name": "B"}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["total"] == 2
    # The nearer portable should never grade worse than the far one.
    a = next(p for p in body["portables"] if p["name"] == "A")
    b = next(p for p in body["portables"] if p["name"] == "B")
    assert a["combined_daq"] >= b["combined_daq"]


def test_repeater_design_endpoint(client):
    r = client.post("/api/rf/repeater/design", json={
        "freq_mhz": 450.0, "system_gain_db": 85.0,
        "donor_coverage_separation_m": 3.0, "arrangement": "vertical",
        "reliable_range_m": 4000.0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "isolation" in body and "cascade" in body
    assert body["cascade"]["spacing_m"] > 0


def test_talkback_unknown_profile_422(client):
    r = client.post("/api/rf/talkback", json={
        "base_lat": 0.02, "base_lon": 0.02,
        "portable_lat": 0.05, "portable_lon": 0.05,
        "portable_profile": "does_not_exist"})
    assert r.status_code == 422
