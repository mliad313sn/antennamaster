"""Phase 3 tests: automated AP placement solver — greedy coverage, capacity
sizing, roaming enforcement, Welsh-Powell channel colouring, and the API."""
import ezdxf
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.rf import apsolver as ap


@pytest.fixture
def client():
    return TestClient(app)


def _open_area(size_m=60.0, demand_m=5.0, cand_m=12.0):
    bbox = (0.0, 0.0, size_m, size_m)
    demand = ap.make_grid(bbox, demand_m)
    candidates = ap.make_grid(bbox, cand_m, inset=cand_m * 0.25)
    return bbox, demand, candidates


# ----------------------------------------------------- channel colouring
def test_welsh_powell_neighbors_differ():
    # A triangle (all mutually interfering) needs 3 distinct channels.
    adj = [{1, 2}, {0, 2}, {0, 1}]
    plan = ap.assign_channels(adj, [36, 40, 44, 48])
    ch = plan["channels"]
    assert ch[0] != ch[1] and ch[1] != ch[2] and ch[0] != ch[2]
    assert plan["cochannel_conflicts"] == 0


def test_welsh_powell_forced_reuse_when_palette_small():
    adj = [{1, 2}, {0, 2}, {0, 1}]           # triangle, but only 2 channels
    plan = ap.assign_channels(adj, [1, 6])
    assert plan["cochannel_conflicts"] >= 1


# ----------------------------------------------------- greedy coverage
def test_more_aps_for_larger_area():
    _, d_small, c_small = _open_area(40.0)
    _, d_big, c_big = _open_area(120.0)
    r_small = ap.build_indoor_rssi(None, c_small, d_small, 5800.0, 1.0, 20.0, 3.0)
    r_big = ap.build_indoor_rssi(None, c_big, d_big, 5800.0, 1.0, 20.0, 3.0)
    s_small = ap.solve_layout(r_small, c_small, d_small, target_rssi_dbm=-67.0)
    s_big = ap.solve_layout(r_big, c_big, d_big, target_rssi_dbm=-67.0)
    assert s_big.ap_count > s_small.ap_count
    assert s_small.coverage_fraction >= 0.9


def test_walls_increase_ap_count():
    """A high-loss (concrete) wall splitting the room needs at least as many
    APs to hold the target as the same geometry with a low-loss (drywall)
    partition — isolating the material effect on a shared FSPL base."""
    bbox, demand, candidates = _open_area(60.0)
    from app.services.indoor.floorplan import WallSet
    ys = np.linspace(0, 60, 40)                 # 40 nodes -> 39 segments
    p0 = np.column_stack([np.full(len(ys) - 1, 30.0), ys[:-1]])
    p1 = np.column_stack([np.full(len(ys) - 1, 30.0), ys[1:]])
    n_seg = p0.shape[0]
    light = WallSet(p0, p1, ["drywall"] * n_seg)
    heavy = WallSet(p0, p1, ["concrete"] * n_seg)
    r_light = ap.build_indoor_rssi(light, candidates, demand, 5800.0, 1.0, 20.0, 3.0)
    r_heavy = ap.build_indoor_rssi(heavy, candidates, demand, 5800.0, 1.0, 20.0, 3.0)
    s_light = ap.solve_layout(r_light, candidates, demand, target_rssi_dbm=-67.0)
    s_heavy = ap.solve_layout(r_heavy, candidates, demand, target_rssi_dbm=-67.0)
    assert s_heavy.ap_count >= s_light.ap_count


# ----------------------------------------------------- capacity sizing
def test_capacity_adds_aps():
    bbox, demand, candidates = _open_area(40.0)
    rssi = ap.build_indoor_rssi(None, candidates, demand, 5800.0, 1.0, 20.0, 3.0)
    base = ap.solve_layout(rssi, candidates, demand, target_rssi_dbm=-67.0)
    # 2000 users at 40/AP forces 50 APs regardless of coverage.
    dense = ap.solve_layout(rssi, candidates, demand, target_rssi_dbm=-67.0,
                            area_m2=1600.0, user_density_per_100m2=125.0,
                            users_per_ap=40, max_aps=200)
    assert dense.capacity["capacity_aps"] >= 40
    assert dense.ap_count > base.ap_count


def test_throughput_capacity():
    bbox, demand, candidates = _open_area(40.0)
    rssi = ap.build_indoor_rssi(None, candidates, demand, 5800.0, 1.0, 20.0, 3.0)
    sol = ap.solve_layout(rssi, candidates, demand, target_rssi_dbm=-67.0,
                          throughput_demand_mbps=6000.0, ap_capacity_mbps=600.0,
                          max_aps=200)
    assert sol.capacity["cap_by_throughput"] == 10


# ----------------------------------------------------- roaming
def test_roaming_fraction_reported():
    bbox, demand, candidates = _open_area(60.0)
    rssi = ap.build_indoor_rssi(None, candidates, demand, 5800.0, 1.0, 20.0, 3.0)
    sol = ap.solve_layout(rssi, candidates, demand, target_rssi_dbm=-67.0,
                          roaming_threshold_dbm=-67.0)
    assert 0.0 <= sol.roaming_fraction <= 1.0


# ----------------------------------------------------- API
def _upload_room_dxf(client):
    doc = ezdxf.new("R2010")
    doc.layers.add("WALLS")
    msp = doc.modelspace()
    # A 50 x 30 m room outline (drawing units = meters).
    msp.add_lwpolyline([(0, 0), (50, 0), (50, 30), (0, 30)],
                       dxfattribs={"layer": "WALLS", "closed": 1})
    import io
    buf = io.StringIO()
    doc.write(buf)
    data = buf.getvalue().encode("utf-8")
    r = client.post("/api/dxf/upload",
                    files={"file": ("room.dxf", data, "application/dxf")})
    assert r.status_code == 200, r.text
    return r.json()["dxf_id"]


def test_ap_solve_endpoint(client):
    dxf_id = _upload_room_dxf(client)
    r = client.post("/api/indoor/ap-solve", json={
        "dxf_id": dxf_id, "layer_materials": {"WALLS": "concrete"},
        "unit_scale": 1.0, "freq_mhz": 5800.0, "target_rssi_dbm": -67.0,
        "demand_spacing_m": 5.0, "candidate_spacing_m": 12.0,
        "user_density_per_100m2": 10.0, "users_per_ap": 40, "band": "5GHz"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ap_count"] >= 1
    assert len(body["aps"]) == body["ap_count"]
    for a in body["aps"]:
        assert "x" in a and "y" in a and "z_m" in a and "channel" in a
        assert a["channel"] in ap.CHANNEL_PLANS["5GHz"]
    assert 0.0 <= body["coverage_fraction"] <= 1.0
