"""Tests for indoor (multi-wall / P.1238) and underground (tunnel / TTE) studies."""
import ezdxf
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.indoor.engine import itu_p1238_loss_db, simulate_indoor
from app.services.indoor.floorplan import extract_walls
from app.services.indoor.materials import guess_material, material_loss_db
from app.services.rf.underground import (tte_link, tte_skin_depth_m,
                                         tunnel_alpha_db_per_m, tunnel_profile)


# ------------------------------------------------------------- underground
def test_tunnel_alpha_frequency_behavior():
    """Waveguide attenuation must FALL with frequency (lam^2 law) - the
    defining physics of tunnel propagation."""
    a_vhf = tunnel_alpha_db_per_m(150.0, 4.0, 3.0, eps_r=5.0)
    a_uhf = tunnel_alpha_db_per_m(450.0, 4.0, 3.0, eps_r=5.0)
    a_gsm = tunnel_alpha_db_per_m(900.0, 4.0, 3.0, eps_r=5.0)
    assert a_vhf > a_uhf > a_gsm > 0.0
    # Wider tunnels attenuate less (1/a^3).
    assert tunnel_alpha_db_per_m(450.0, 8.0, 3.0) < a_uhf


def test_tunnel_profile_range():
    res = tunnel_profile(450.0, 4.0, 3.0, 5000.0, eps_r=5.0,
                         tx_power_dbm=37.0, tx_gain_dbi=6.0,
                         rx_sensitivity_dbm=-110.0)
    assert res["alpha_db_per_m"] > 0
    assert res["breakpoint_m"] > 0
    assert 0 < res["max_range_m"] <= 5000.0
    powers = [p["rx_power_dbm"] for p in res["points"]]
    assert powers[0] > powers[-1]              # monotone decay overall


def test_tte_skin_depth_and_link():
    # delta = 503/sqrt(f*sigma): 5 kHz, 0.01 S/m -> ~71 m.
    assert tte_skin_depth_m(5000.0, 0.01) == pytest.approx(71.2, abs=1.0)
    ok = tte_link(3000.0, 80.0, 0.01, tx_power_dbm=30, system_gain_db=20,
                  rx_sensitivity_dbm=-130)
    deep = tte_link(3000.0, 500.0, 0.01, tx_power_dbm=30, system_gain_db=20,
                    rx_sensitivity_dbm=-130)
    assert ok["served"] and not deep["served"]
    # Higher frequency through the same ground = more loss.
    hf = tte_link(100_000.0, 80.0, 0.01)
    assert hf["total_loss_db"] > ok["total_loss_db"]


# ------------------------------------------------------------------ indoor
def test_material_interpolation_and_guess():
    assert material_loss_db("concrete", 900.0) == pytest.approx(10.0)
    assert material_loss_db("concrete", 5800.0) == pytest.approx(20.0)
    mid = material_loss_db("concrete", 2400.0)
    assert 10.0 < mid < 20.0
    assert guess_material("A-WALL-CONC concrete") == "concrete"
    assert guess_material("WINDOWS") == "glass"
    assert guess_material("random123") == "drywall"
    with pytest.raises(ValueError):
        material_loss_db("vibranium", 2400.0)


def test_p1238_indoor_model():
    L1 = itu_p1238_loss_db(np.array([10.0]), 2400.0, 0, "office")[0]
    L2 = itu_p1238_loss_db(np.array([10.0]), 2400.0, 2, "office")[0]
    assert L2 > L1 + 10.0                      # floors cost real dB
    # 2.4 GHz @ 10 m office, same floor: 20log10(2400)+30-28 ~= 69.6 dB
    assert L1 == pytest.approx(69.6, abs=1.0)


def _office_dxf(tmp_path):
    """20 x 10 m office: outer concrete shell, one brick partition mid-plan."""
    doc = ezdxf.new("R2010")
    doc.layers.add("SHELL"); doc.layers.add("PARTITION"); doc.layers.add("FURNITURE")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (20, 0), (20, 10), (0, 10)], close=True,
                       dxfattribs={"layer": "SHELL"})
    msp.add_line((10, 0), (10, 10), dxfattribs={"layer": "PARTITION"})
    msp.add_circle((15, 5), 0.5, dxfattribs={"layer": "FURNITURE"})
    path = tmp_path / "office.dxf"
    doc.saveas(path)
    return path


def test_wall_extraction_and_crossing_loss(tmp_path):
    doc = ezdxf.readfile(str(_office_dxf(tmp_path)))
    walls = extract_walls(doc, {"SHELL": "concrete", "PARTITION": "brick"})
    assert walls.count == 5                    # 4 shell sides + 1 partition
    res = simulate_indoor(walls, tx_x=5.0, tx_y=5.0, freq_mhz=2442.0,
                          grid_px=80, raster_px=200)
    assert res.png[:8] == b"\x89PNG\r\n\x1a\n"
    assert res.stats["walls"] == 5
    # The TX side of the partition must be better served than the far side:
    # rebuild the margin from a paired run without walls to compare.
    free = simulate_indoor(extract_walls(doc, {}), tx_x=5.0, tx_y=5.0,
                           freq_mhz=2442.0, grid_px=80, raster_px=200)
    assert free.stats["min_rx_power_dbm"] > res.stats["min_rx_power_dbm"]
    assert res.stats["served_area_fraction"] <= free.stats["served_area_fraction"] + 1e-9


# --------------------------------------------------------------- API layer
@pytest.fixture
def client():
    return TestClient(app)


def test_indoor_api_workflow(client, tmp_path):
    path = _office_dxf(tmp_path)
    with open(path, "rb") as fh:
        up = client.post("/api/dxf/upload",
                         files={"file": ("office.dxf", fh, "application/dxf")})
    dxf_id = up.json()["dxf_id"]

    # Materials + presets available.
    mats = client.get("/api/indoor/materials").json()["materials"]
    assert any(m["key"] == "concrete" for m in mats)
    presets = client.get("/api/indoor/presets").json()
    assert presets["tunnel_walls"] and presets["earth"]

    # Preview PNG with plan bounds header.
    pv = client.get(f"/api/indoor/{dxf_id}/preview.png",
                    params={"layers": "SHELL,PARTITION"})
    assert pv.status_code == 200
    assert pv.headers["x-plan-bounds"].count(",") == 3

    # Coverage with the Wi-Fi preset.
    resp = client.post("/api/indoor/coverage", json={
        "dxf_id": dxf_id,
        "layer_materials": {"SHELL": "concrete", "PARTITION": "brick"},
        "tx_x": 5.0, "tx_y": 5.0, "technology": "wifi2400", "grid_px": 60,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stats"]["walls"] == 5
    png = client.get(body["png_url"])
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"


def test_tunnel_and_tte_api(client):
    t = client.get("/api/indoor/tunnel", params={
        "freq_mhz": 450, "width_m": 4, "height_m": 3, "length_m": 3000,
        "wall": "rock", "rx_sensitivity_dbm": -110}).json()
    assert t["max_range_m"] > 100
    assert len(t["points"]) == 200

    e = client.get("/api/indoor/tte", params={
        "freq_hz": 5000, "depth_m": 100, "earth": "dry_rock"}).json()
    assert "margin_db" in e and "skin_depth_m" in e
    assert client.get("/api/indoor/tte", params={"earth": "cheese"}).status_code == 422
