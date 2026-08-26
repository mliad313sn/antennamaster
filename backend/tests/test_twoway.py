"""Tests: two-way talk-back link/area analysis, DAQ grading, repeater cascade."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.rf.twoway import (daq_grade, repeater_cascade,
                                    twoway_coverage, twoway_evaluate_receiver)
from app.services.terrain.coverage import CoverageEngine
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


# A VHF public-safety repeater vs a 5 W / 1.5 W portable.
BASE = {"freq_mhz": 155.0, "model": "okumura_hata", "environment": "suburban",
        "h_bs_m": 40.0, "tx_power_dbm": 44.0, "ant_gain_dbi": 6.0,
        "rx_sensitivity_dbm": -119.0, "losses_db": 3.0}
PORT_5W = {"tx_power_dbm": 37.0, "ant_gain_dbi": 0.0,
           "rx_sensitivity_dbm": -119.0, "h_ut_m": 1.5,
           "body_loss_db": 4.0, "penetration_class": "on_street"}


# ------------------------------------------------------------- unit: DAQ
def test_daq_grade_monotonic_and_anchored():
    sens, fm = -119.0, 20.0
    anchor = sens + fm            # -99 dBm -> exactly DAQ 3.4
    assert daq_grade(anchor, sens, fm)["daq"] == 3.4
    assert daq_grade(anchor + 10, sens, fm)["daq"] == 4.5
    assert daq_grade(anchor - 10, sens, fm)["daq"] == 2.0
    assert daq_grade(anchor - 30, sens, fm)["daq"] == 1.0
    # Monotonic non-decreasing in received level.
    levels = np.linspace(sens - 5, sens + 40, 40)
    daqs = [daq_grade(x, sens, fm)["daq"] for x in levels]
    assert daqs == sorted(daqs)


# ---------------------------------------------------- unit: bidirectional link
def test_talkback_limited_by_talk_in_when_portable_weaker(fake_store):
    fusion = TerrainFusionService(store=fake_store)
    # Base runs 44 dBm, portable only 30 dBm (1 W): talk-in must be the
    # limiting direction (weaker TX into the same reciprocal path).
    port_1w = dict(PORT_5W, tx_power_dbm=30.0)
    res = twoway_evaluate_receiver(fusion, dict(BASE), port_1w,
                                   47.0, 15.0, 47.0, 15.05)
    assert res["limiting_direction"] == "talk_in"
    # Talk-out (44 dBm base) must deliver a stronger RX than talk-in (30 dBm).
    assert res["talk_out"]["rx_power_dbm"] > res["talk_in"]["rx_power_dbm"]
    # The reciprocity invariant: the two RX levels differ by exactly the TX
    # power swap (30 - 44 = -14 dB).
    delta = res["talk_in"]["rx_power_dbm"] - res["talk_out"]["rx_power_dbm"]
    assert delta == pytest.approx(30.0 - 44.0, abs=0.15)


def test_symmetric_power_gives_symmetric_directions(fake_store):
    fusion = TerrainFusionService(store=fake_store)
    # Equal TX power and equal sensitivity -> both directions identical.
    port = dict(PORT_5W, tx_power_dbm=44.0)
    res = twoway_evaluate_receiver(fusion, dict(BASE), port,
                                   47.0, 15.0, 47.0, 15.03)
    assert res["talk_out"]["rx_power_dbm"] == pytest.approx(
        res["talk_in"]["rx_power_dbm"], abs=0.05)
    assert res["worst_daq"] == min(res["talk_out"]["daq"], res["talk_in"]["daq"])


def test_penetration_and_body_loss_reduce_both_directions(fake_store):
    fusion = TerrainFusionService(store=fake_store)
    street = twoway_evaluate_receiver(fusion, dict(BASE), dict(PORT_5W),
                                      47.0, 15.0, 47.0, 15.03)
    heavy = dict(PORT_5W, penetration_class="heavy_building")
    indoor = twoway_evaluate_receiver(fusion, dict(BASE), heavy,
                                      47.0, 15.0, 47.0, 15.03)
    # 20 dB building penetration hits both talk-out and talk-in.
    assert indoor["talk_out"]["rx_power_dbm"] == pytest.approx(
        street["talk_out"]["rx_power_dbm"] - 20.0, abs=0.1)
    assert indoor["talk_in"]["rx_power_dbm"] == pytest.approx(
        street["talk_in"]["rx_power_dbm"] - 20.0, abs=0.1)


# ----------------------------------------------------------- unit: area study
def test_twoway_coverage_reliable_is_intersection(fake_store):
    engine = CoverageEngine(TerrainFusionService(store=fake_store))
    port_1w = dict(PORT_5W, tx_power_dbm=30.0)
    res = twoway_coverage(engine, dict(BASE), port_1w, 47.0, 15.0,
                          radius_m=6000.0, n_radials=48, n_steps=32)
    # Reliable (both) area can never exceed either single-direction area.
    assert res["reliable_talkback_fraction"] <= res["talk_out_area_fraction"] + 1e-9
    assert res["reliable_talkback_fraction"] <= res["talk_in_area_fraction"] + 1e-9
    # With a weaker portable, talk-in is the smaller footprint.
    assert res["talk_in_area_fraction"] <= res["talk_out_area_fraction"] + 1e-9
    # Limiting-direction split sums back to the reliable area.
    assert (res["reliable_limited_by_talk_in"]
            + res["reliable_limited_by_talk_out"]) == pytest.approx(
        res["reliable_talkback_fraction"], abs=1e-3)


# ------------------------------------------------------- unit: repeater chain
def test_repeater_cascade_spacing_and_count():
    r = repeater_cascade(corridor_km=30.0, reliable_range_km=5.0,
                         overlap_pct=20.0)
    # spacing = 2*5*(1-0.2) = 8 km -> ceil(30/8) = 4 repeaters.
    assert r["spacing_km"] == pytest.approx(8.0)
    assert r["repeaters"] == 4
    assert len(r["positions_km"]) == 4
    with pytest.raises(ValueError):
        repeater_cascade(10.0, 0.0)


# ------------------------------------------------------------- API layer
def test_twoway_link_api(client):
    body = {"base": {"freq_mhz": 155.0, "model": "okumura_hata",
                     "environment": "suburban", "h_bs_m": 40.0,
                     "tx_power_dbm": 44.0, "ant_gain_dbi": 6.0,
                     "rx_sensitivity_dbm": -119.0, "losses_db": 3.0},
            "portable": {"tx_power_dbm": 30.0, "ant_gain_dbi": 0.0,
                         "rx_sensitivity_dbm": -119.0, "h_ut_m": 1.5,
                         "penetration_class": "light_building"},
            "tx_lat": 47.0, "tx_lon": 15.0, "rx_lat": 47.0, "rx_lon": 15.04}
    resp = client.post("/api/rf/twoway/link", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["limiting_direction"] == "talk_in"
    assert "talk_out" in data and "talk_in" in data
    assert set(("daq", "label")) <= data["talk_out"].keys()


def test_twoway_coverage_api(client):
    body = {"base": {"freq_mhz": 155.0, "model": "okumura_hata",
                     "environment": "suburban", "h_bs_m": 40.0,
                     "tx_power_dbm": 44.0, "ant_gain_dbi": 6.0,
                     "rx_sensitivity_dbm": -119.0, "losses_db": 3.0},
            "portable": {"tx_power_dbm": 37.0, "ant_gain_dbi": 0.0,
                         "rx_sensitivity_dbm": -119.0, "h_ut_m": 1.5},
            "lat": 47.0, "lon": 15.0, "radius_km": 6.0,
            "n_radials": 48, "n_steps": 32}
    resp = client.post("/api/rf/twoway/coverage", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert 0.0 <= data["reliable_talkback_fraction"] <= 1.0
    assert data["reliable_talkback_fraction"] <= data["talk_out_area_fraction"] + 1e-6


# --------------------------------------------------- target_daq in area study
def test_area_talkback_honours_target_daq(fake_store):
    """target_daq used to be accepted, echoed and ignored: the area study
    pinned its anchors to DAQ 3.4, so a tender quoting "reliable at DAQ 4.5"
    silently reported the 3.4 number for every grade."""
    engine = CoverageEngine(TerrainFusionService(store=fake_store))
    runs = {}
    for daq in (3.0, 3.4, 4.0, 4.5):
        runs[daq] = twoway_coverage(engine, dict(BASE), dict(PORT_5W),
                                    47.0, 15.0, radius_m=12_000.0,
                                    n_radials=48, n_steps=32, target_daq=daq)

    fracs = [runs[d]["reliable_talkback_fraction"] for d in (3.0, 3.4, 4.0, 4.5)]
    # A stricter audio grade can never be met over MORE area.
    assert fracs == sorted(fracs, reverse=True), fracs
    assert fracs[0] > fracs[-1], "the requested grade must change the answer"

    # The anchors are reported and move by the published DAQ offsets.
    assert (runs[4.5]["anchor_out_dbm"] - runs[3.4]["anchor_out_dbm"]
            == pytest.approx(10.0, abs=0.05))
    assert (runs[3.0]["anchor_in_dbm"] - runs[3.4]["anchor_in_dbm"]
            == pytest.approx(-4.0, abs=0.05))


def test_daq_offset_matches_the_published_grade_table():
    from app.services.rf.twoway import daq_offset_db
    assert daq_offset_db(3.4) == 0.0          # the reference anchor
    assert daq_offset_db(4.0) == 6.0
    assert daq_offset_db(4.5) == 10.0
    assert daq_offset_db(3.0) == -4.0
