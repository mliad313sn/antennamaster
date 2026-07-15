"""Tests: drone LiDAR → DSM ingestion and diffraction against real 3D objects."""
import io

import laspy
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pyproj import Transformer

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.lidar.pointcloud import build_dsm_grid, parse_las
from app.services.terrain.fusion import TerrainFusionService

# A UTM-33N survey centred near lon 15, lat 47.
_EPSG = 32633
_FWD = Transformer.from_crs("EPSG:4326", f"EPSG:{_EPSG}", always_xy=True)
CX, CY = _FWD.transform(15.0, 47.0)


def _make_las(ground_z=200.0, building_z=230.0, epsg=_EPSG) -> bytes:
    """Synthetic cloud: a 200x200 m ground plane at ground_z with a 40x40 m
    building block at building_z in the centre, classified (2=ground, 6=bldg)."""
    rng = np.random.default_rng(0)
    n = 8000
    gx = CX + rng.uniform(-100, 100, n)
    gy = CY + rng.uniform(-100, 100, n)
    gz = np.full(n, ground_z)
    cls = np.full(n, 2, dtype=np.uint8)
    # Building footprint: raise z and reclassify inside a 40 m box.
    inb = (np.abs(gx - CX) < 20) & (np.abs(gy - CY) < 20)
    gz[inb] = building_z
    cls[inb] = 6
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.offsets = [CX, CY, 0]
    header.scales = [0.01, 0.01, 0.01]
    try:
        header.add_crs(__import__("pyproj").CRS.from_epsg(epsg))
    except Exception:
        pass
    las = laspy.LasData(header)
    las.x, las.y, las.z = gx, gy, gz
    las.classification = cls
    buf = io.BytesIO()
    las.write(buf)
    return buf.getvalue()


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


# ------------------------------------------------------- unit: parse + DSM
def test_parse_las_roundtrip():
    pc = parse_las(_make_las())
    assert pc["n_points"] == 8000
    assert 195 <= min(pc["z"]) <= 205 and max(pc["z"]) >= 229
    # bounds span ~200 m around the centre.
    assert pc["bounds"][2] - pc["bounds"][0] > 150


def test_dsm_captures_building_top():
    pc = parse_las(_make_las(ground_z=200.0, building_z=230.0))
    grid, stats = build_dsm_grid(pc["x"], pc["y"], pc["z"], cell_m=2.0,
                                 classification=pc["classification"])
    # The DSM max is the building roof; the surface floor is the ground.
    assert stats["surface_max_m"] == pytest.approx(230.0, abs=1.0)
    assert stats["surface_min_m"] == pytest.approx(200.0, abs=1.0)
    # Object height (DSM - DTM) recovers the ~30 m building.
    assert stats["max_object_height_m"] == pytest.approx(30.0, abs=2.0)
    # Sampling the grid centre returns the roof height.
    zc = grid.sample(np.array([CX]), np.array([CY]))[0]
    assert zc == pytest.approx(230.0, abs=1.5)


def test_empty_cloud_rejected():
    with pytest.raises(ValueError):
        build_dsm_grid(np.array([]), np.array([]), np.array([]))


# ------------------------------------------------------------- API layer
def test_lidar_upload_and_profile_shows_obstruction(client):
    # Ground ~matches the fake SRTM here (~371 m); a 50 m building rises above
    # it, so the surveyed surface genuinely obstructs the low link.
    up = client.post("/api/lidar/upload",
                     files={"file": ("survey.las",
                                     _make_las(ground_z=370.0, building_z=420.0),
                                     "application/octet-stream")},
                     data={"cell_m": "2.0"})
    assert up.status_code == 200, up.text
    body = up.json()
    dsm_id = body["dsm_id"]
    assert body["n_points"] == 8000
    assert body["stats"]["surface_max_m"] == pytest.approx(420.0, abs=1.5)

    # A low-antenna link straight across the building: diffraction against the
    # surveyed surface must exceed the bare-terrain diffraction.
    prof = client.get(f"/api/lidar/{dsm_id}/profile", params={
        "lat1": 47.0, "lon1": 14.9987, "lat2": 47.0, "lon2": 15.0013,
        "h_tx_m": 2.0, "h_rx_m": 2.0, "freq_mhz": 2400.0, "samples": 128})
    assert prof.status_code == 200, prof.text
    d = prof.json()
    assert d["max_obstruction_m"] > 10.0     # the building shows up
    assert d["extra_loss_from_surface_db"] > 0.0
    assert d["surface"]["diffraction_loss_db"] >= d["bare_terrain"]["diffraction_loss_db"]


def test_lidar_unknown_dsm_404(client):
    assert client.get("/api/lidar/nope/info").status_code == 404
