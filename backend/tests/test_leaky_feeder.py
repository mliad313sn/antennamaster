"""Phase 2 tests: radiating-cable (leaky feeder) physics, auto amplifier
spacing, moving-train KPI, and DXF cable-run measurement."""
import ezdxf
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.rf import underground as ug
from app.services.indoor.floorplan import layer_polyline_length


@pytest.fixture
def client():
    return TestClient(app)


# ------------------------------------------------------- cable physics
def test_cable_loss_rises_with_frequency():
    lo = ug.leaky_cable_loss_db_per_m(150.0, 3.5, 450.0)
    hi = ug.leaky_cable_loss_db_per_m(1800.0, 3.5, 450.0)
    assert hi > lo
    # sqrt(1800/450) = 2 -> loss doubles vs the 450 MHz reference.
    ref = ug.leaky_cable_loss_db_per_m(450.0, 3.5, 450.0)
    assert hi == pytest.approx(ref * 2.0, rel=1e-6)


def test_amplifier_spacing_shrinks_with_higher_threshold():
    loss = ug.leaky_cable_loss_db_per_m(450.0, 3.5, 450.0)
    wide = ug.amplifier_spacing_m(20.0, -95.0, 68.0, loss)
    tight = ug.amplifier_spacing_m(20.0, -80.0, 68.0, loss)   # higher threshold
    assert tight < wide


# --------------------------------------------------- full profile
def test_leaky_feeder_amplifiers_hold_service():
    """A long run WITH auto amplifiers should keep continuous service; the
    SAME run WITHOUT amplifiers must drop out further along."""
    common = dict(freq_mhz=450.0, cable_length_m=4000.0, cable="rc78",
                  head_end_dbm=20.0, rx_sensitivity_dbm=-95.0,
                  design_margin_db=10.0)
    amped = ug.leaky_feeder_profile(auto_amplifiers=True, **common)
    bare = ug.leaky_feeder_profile(auto_amplifiers=False, **common)
    assert amped["amplifier_count"] >= 1
    assert amped["continuous_service_pct"] > bare["continuous_service_pct"]
    assert bare["amplifier_count"] == 0


def test_moving_train_kpi_flags_gap():
    # Very lossy short cable, no amps, weak head-end -> a coverage gap exists.
    r = ug.leaky_feeder_profile(freq_mhz=1800.0, cable_length_m=2000.0,
                                cable="rc12", head_end_dbm=-5.0,
                                auto_amplifiers=False, rx_sensitivity_dbm=-95.0,
                                design_margin_db=10.0)
    assert r["worst_gap_m"] > 0.0
    assert r["moving_train_ok"] is False
    assert 0.0 <= r["continuous_service_pct"] <= 100.0


def test_radial_distance_reduces_rx():
    near = ug.leaky_feeder_profile(freq_mhz=450.0, cable_length_m=1000.0,
                                   radial_distance_m=2.0)
    far = ug.leaky_feeder_profile(freq_mhz=450.0, cable_length_m=1000.0,
                                  radial_distance_m=8.0)
    assert far["radial_loss_db"] > near["radial_loss_db"]
    assert far["points"][0]["rx_power_dbm"] < near["points"][0]["rx_power_dbm"]


# --------------------------------------------------- DXF cable run
def test_layer_polyline_length():
    doc = ezdxf.new("R2010")
    doc.layers.add("CABLE")
    msp = doc.modelspace()
    # A 300 m + 400 m dogleg = 700 drawing units.
    msp.add_lwpolyline([(0, 0), (300, 0), (300, 400)],
                       dxfattribs={"layer": "CABLE"})
    length = layer_polyline_length(doc, "CABLE", unit_scale=1.0)
    assert length == pytest.approx(700.0)
    # unit_scale converts drawing units -> meters.
    assert layer_polyline_length(doc, "CABLE", unit_scale=0.5) == pytest.approx(350.0)


# --------------------------------------------------- API
def test_leaky_cables_endpoint(client):
    r = client.get("/api/indoor/leaky-cables")
    assert r.status_code == 200
    assert any(c["key"] == "rc78" for c in r.json()["cables"])


def test_leaky_feeder_endpoint(client):
    r = client.post("/api/indoor/leaky-feeder", json={
        "freq_mhz": 450.0, "cable": "rc78", "cable_length_m": 3000.0,
        "head_end_dbm": 20.0, "design_margin_db": 10.0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cable_length_m"] == 3000.0
    assert "continuous_service_pct" in body
    assert "amplifier_positions_m" in body


def test_leaky_feeder_requires_length_or_dxf(client):
    r = client.post("/api/indoor/leaky-feeder", json={"freq_mhz": 450.0})
    assert r.status_code == 422
