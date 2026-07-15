"""Tests: DAS tree solver + combined coverage + multi-floor stack (C6)."""
import ezdxf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.indoor.das import DasError, das_coverage, solve_das
from app.services.indoor.floorplan import extract_walls

client = TestClient(app)


def _office_dxf(tmp_path, name="office.dxf"):
    doc = ezdxf.new("R2010")
    doc.layers.add("SHELL"); doc.layers.add("PARTITION")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (40, 0), (40, 20), (0, 20)], close=True,
                       dxfattribs={"layer": "SHELL"})
    msp.add_line((20, 0), (20, 20), dxfattribs={"layer": "PARTITION"})
    path = tmp_path / name
    doc.saveas(path)
    return path


def _tree_two_antennas():
    return {"component": "cable", "length_m": 20, "loss_db_per_100m": 10,
            "children": [{
                "component": "splitter", "ways": 2, "excess_db": 0.5,
                "children": [
                    {"component": "cable", "length_m": 10, "loss_db_per_100m": 10,
                     "children": [{"component": "antenna", "x": 10, "y": 10,
                                   "gain_dbi": 2.0}]},
                    {"component": "cable", "length_m": 30, "loss_db_per_100m": 10,
                     "children": [{"component": "antenna", "x": 30, "y": 10,
                                   "gain_dbi": 2.0}]},
                ]}]}


# ------------------------------------------------------------- unit: solver
def test_das_power_accounting_exact():
    ants = solve_das(30.0, _tree_two_antennas())
    assert len(ants) == 2
    # Branch A: 30 − 2 (20m cable) − (3.01+0.5) split − 1 (10m cable) = 23.49 dBm
    a = next(x for x in ants if x["x"] == 10)
    assert a["input_power_dbm"] == pytest.approx(30 - 2 - 3.51 - 1, abs=0.02)
    assert a["eirp_dbm"] == pytest.approx(a["input_power_dbm"] + 2.0, abs=1e-6)
    # Branch B has 20 m more cable: exactly 2 dB weaker.
    b = next(x for x in ants if x["x"] == 30)
    assert a["input_power_dbm"] - b["input_power_dbm"] == pytest.approx(2.0, abs=0.02)


def test_das_coupler_split():
    tree = {"component": "coupler", "coupling_db": 10.0, "insertion_db": 0.5,
            "children": [
                {"component": "antenna", "x": 0, "y": 0, "gain_dbi": 0},
                {"component": "antenna", "x": 5, "y": 0, "gain_dbi": 0}]}
    ants = solve_das(20.0, tree)
    through = next(x for x in ants if x["x"] == 0)
    tap = next(x for x in ants if x["x"] == 5)
    assert tap["input_power_dbm"] == pytest.approx(10.0, abs=1e-6)   # −10 dB tap
    # Through port: −10·log10(1−0.1) − 0.5 ≈ −0.96 dB total.
    assert through["input_power_dbm"] == pytest.approx(20 - 0.958, abs=0.05)


def test_das_tree_validation():
    with pytest.raises(DasError):
        solve_das(20, {"component": "cable", "length_m": 5,
                       "loss_db_per_100m": 10, "children": []})
    with pytest.raises(DasError):
        solve_das(20, {"component": "splitter", "ways": 2, "children": [
            {"component": "antenna", "x": 0, "y": 0}]})
    with pytest.raises(DasError):
        solve_das(20, {"component": "warp_drive"})
    with pytest.raises(DasError):   # no antennas at all
        solve_das(20, {"component": "cable", "length_m": 5,
                       "loss_db_per_100m": 10, "children": [
                           {"component": "cable", "length_m": 5,
                            "loss_db_per_100m": 10, "children": [
                                {"component": "antenna", "x": 0, "y": 0,
                                 "gain_dbi": 0, "children": [
                                     {"component": "antenna", "x": 1, "y": 1}]}]}]})


# ------------------------------------------------- unit: combined coverage
def test_two_antennas_cover_at_least_one(tmp_path):
    doc = ezdxf.readfile(str(_office_dxf(tmp_path)))
    walls = extract_walls(doc, {"SHELL": "concrete", "PARTITION": "brick"})
    one = das_coverage(walls, [{"x": 10, "y": 10, "gain_dbi": 2,
                                "input_power_dbm": 18.0}], 2442.0, grid_px=80)
    two = das_coverage(walls, [{"x": 10, "y": 10, "gain_dbi": 2,
                                "input_power_dbm": 18.0},
                               {"x": 30, "y": 10, "gain_dbi": 2,
                                "input_power_dbm": 18.0}], 2442.0, grid_px=80)
    assert two.stats["served_area_fraction"] \
        >= one.stats["served_area_fraction"]
    assert two.stats["antennas"] == 2
    assert two.png[:8] == b"\x89PNG\r\n\x1a\n"


# ------------------------------------------------------------- API layer
def _upload(tmp_path, name):
    with open(_office_dxf(tmp_path, name), "rb") as fh:
        up = client.post("/api/dxf/upload",
                         files={"file": (name, fh, "application/dxf")})
    return up.json()["dxf_id"]


def test_das_api(tmp_path):
    dxf_id = _upload(tmp_path, "das.dxf")
    r = client.post("/api/indoor/das", json={
        "dxf_id": dxf_id,
        "layer_materials": {"SHELL": "concrete", "PARTITION": "brick"},
        "freq_mhz": 2442.0, "source_power_dbm": 30.0,
        "tree": _tree_two_antennas(), "grid_px": 80})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["antennas"]) == 2
    assert d["stats"]["served_area_fraction"] > 0
    # Invalid tree -> 422 with the reason.
    bad = client.post("/api/indoor/das", json={
        "dxf_id": dxf_id, "layer_materials": {"SHELL": "concrete"},
        "tree": {"component": "warp_drive"}})
    assert bad.status_code == 422


def test_floor_stack_api(tmp_path):
    g = _upload(tmp_path, "ground.dxf")
    u1 = _upload(tmp_path, "first.dxf")
    u2 = _upload(tmp_path, "second.dxf")
    r = client.post("/api/indoor/stack", json={
        "floors": [
            {"level": 0, "dxf_id": g,
             "layer_materials": {"SHELL": "concrete", "PARTITION": "brick"}},
            {"level": 1, "dxf_id": u1,
             "layer_materials": {"SHELL": "concrete", "PARTITION": "brick"}},
            {"level": 2, "dxf_id": u2,
             "layer_materials": {"SHELL": "concrete", "PARTITION": "brick"}},
        ],
        "tx_level": 0, "tx_x": 10.0, "tx_y": 10.0,
        "freq_mhz": 2442.0, "grid_px": 60})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["floors"]) == 3
    served = {f["level"]: f["stats"]["served_area_fraction"]
              for f in d["floors"]}
    # Coverage must not improve as storeys are crossed.
    assert served[0] >= served[1] >= served[2]
    assert d["floors"][1]["floors_crossed"] == 1
    assert d["floors"][2]["floors_crossed"] == 2
    assert 0 <= d["building_mean_served_fraction"] <= 1
