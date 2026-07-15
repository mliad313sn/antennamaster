"""Tests: automated AP placement, channel plan, capacity floor, roaming."""
import ezdxf
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.indoor.floorplan import extract_walls
from app.services.indoor.placement import auto_place_aps

client = TestClient(app)


def _warehouse_dxf(tmp_path):
    """60 x 40 m warehouse: concrete shell + two internal brick partitions."""
    doc = ezdxf.new("R2010")
    doc.layers.add("SHELL"); doc.layers.add("PARTITION")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (60, 0), (60, 40), (0, 40)], close=True,
                       dxfattribs={"layer": "SHELL"})
    msp.add_line((20, 0), (20, 40), dxfattribs={"layer": "PARTITION"})
    msp.add_line((40, 0), (40, 40), dxfattribs={"layer": "PARTITION"})
    path = tmp_path / "wh.dxf"
    doc.saveas(path)
    return path


def _walls(tmp_path):
    doc = ezdxf.readfile(str(_warehouse_dxf(tmp_path)))
    return extract_walls(doc, {"SHELL": "concrete", "PARTITION": "brick"})


# --------------------------------------------------------- unit: placement
def test_auto_place_reaches_coverage_target(tmp_path):
    walls = _walls(tmp_path)
    res = auto_place_aps(walls, 2442.0, rx_sensitivity_dbm=-72.0,
                         coverage_target=0.9, max_aps=16)
    assert res["ap_count"] >= 1
    assert res["coverage_fraction"] >= 0.85     # meets (or nearly) the target
    # Each placed AP has a position inside the plan bounds and a channel.
    x0, y0, x1, y1 = res["bounds_dxf"]
    for ap in res["access_points"]:
        assert x0 <= ap["x"] <= x1 and y0 <= ap["y"] <= y1
        assert ap["channel"] in (1, 6, 11)


def test_lower_sensitivity_needs_more_aps(tmp_path):
    walls = _walls(tmp_path)
    easy = auto_place_aps(walls, 2442.0, rx_sensitivity_dbm=-80.0,
                          coverage_target=0.9, max_aps=20)
    hard = auto_place_aps(walls, 2442.0, rx_sensitivity_dbm=-60.0,
                          coverage_target=0.9, max_aps=20)
    # A stricter (higher) required level shrinks each AP's reach -> more APs.
    assert hard["ap_count"] >= easy["ap_count"]


def test_capacity_floor_forces_more_aps(tmp_path):
    walls = _walls(tmp_path)
    base = auto_place_aps(walls, 2442.0, rx_sensitivity_dbm=-80.0,
                          coverage_target=0.9, max_aps=30)
    # 1200 users x 5 Mbps / 600 Mbps per AP = 10 APs minimum.
    cap = auto_place_aps(walls, 2442.0, rx_sensitivity_dbm=-80.0,
                         coverage_target=0.9, max_aps=30,
                         users_total=1200, throughput_per_user_mbps=5.0,
                         ap_capacity_mbps=600.0)
    assert cap["capacity_floor_aps"] == 10
    assert cap["ap_count"] >= base["ap_count"]
    assert cap["ap_count"] >= 10


def test_channel_plan_diversifies_neighbours(tmp_path):
    walls = _walls(tmp_path)
    res = auto_place_aps(walls, 2442.0, rx_sensitivity_dbm=-60.0,
                         coverage_target=0.95, max_aps=20, band="2.4GHz")
    # With several APs the plan must actually use more than one channel.
    if res["ap_count"] >= 3:
        assert len(res["channels_used"]) >= 2
        assert set(res["channels_used"]) <= {1, 6, 11}


def test_roaming_fraction_reported(tmp_path):
    walls = _walls(tmp_path)
    res = auto_place_aps(walls, 2442.0, rx_sensitivity_dbm=-72.0,
                         coverage_target=0.95, max_aps=20,
                         roaming_threshold_dbm=-67.0)
    assert 0.0 <= res["roaming_ready_fraction"] <= 1.0


# ------------------------------------------------------------- API layer
def test_auto_place_api(tmp_path):
    path = _warehouse_dxf(tmp_path)
    with open(path, "rb") as fh:
        up = client.post("/api/dxf/upload",
                         files={"file": ("wh.dxf", fh, "application/dxf")})
    dxf_id = up.json()["dxf_id"]
    body = {"dxf_id": dxf_id,
            "layer_materials": {"SHELL": "concrete", "PARTITION": "brick"},
            "unit_scale": 1.0, "freq_mhz": 2442.0,
            "rx_sensitivity_dbm": -72.0, "coverage_target": 0.9,
            "max_aps": 16, "band": "5GHz"}
    resp = client.post("/api/indoor/auto-place", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ap_count"] >= 1
    assert data["band"] == "5GHz"
    assert all(ap["channel"] in [36, 40, 44, 48, 149, 153, 157, 161]
               for ap in data["access_points"])
