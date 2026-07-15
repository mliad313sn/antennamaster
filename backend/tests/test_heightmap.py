"""Tests: Cesium 3D terrain heightmap tiles from the fused DEM."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.terrain.fusion import TerrainFusionService
from app.services.terrain.heightmap import heightmap_int16, tile_rectangle


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


def test_tile_rectangle_covers_globe_at_root():
    # Level 0: two tiles in X, one in Y, together spanning the whole globe.
    w0, s0, e0, n0 = tile_rectangle(0, 0, 0)
    w1, s1, e1, n1 = tile_rectangle(0, 1, 0)
    assert (w0, e0) == (-180.0, 0.0)
    assert (w1, e1) == (0.0, 180.0)
    assert (s0, n0) == (-90.0, 90.0)


def test_heightmap_matches_fake_ramp(fake_store):
    # The fake world ramps west->east; a tile's heights must therefore
    # increase along each row (west to east).
    fusion = TerrainFusionService(store=fake_store)
    raw = heightmap_int16(fusion, 4, 8, 4, size=33)
    arr = np.frombuffer(raw, dtype=np.int16).reshape(33, 33)
    assert arr.shape == (33, 33)
    # Monotonic increase eastward (allow ties from int rounding).
    assert arr[0, -1] >= arr[0, 0]
    assert np.all(np.diff(arr[0].astype(int)) >= 0)


def test_heightmap_api(client):
    resp = client.get("/api/terrain/heightmap/5/16/8.bin", params={"size": 33})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/octet-stream"
    assert resp.headers["x-heightmap-size"] == "33"
    arr = np.frombuffer(resp.content, dtype=np.int16)
    assert arr.size == 33 * 33


def test_heightmap_rejects_bad_tile(client):
    assert client.get("/api/terrain/heightmap/99/0/0.bin").status_code == 422
