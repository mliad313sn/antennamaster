"""Tests for the offline base-map tile server and the pre-download math."""
from fastapi.testclient import TestClient

from app.main import app
from app.services import basemap
from tools.download_basemap import deg2tile, tile_range

client = TestClient(app)


def test_placeholder_is_a_valid_png():
    data = basemap.placeholder_tile()
    assert data[:4] == b"\x89PNG"
    assert len(data) > 100


def test_offline_tile_serves_placeholder_without_network():
    # offline=true forces disk-only; an uncached tile returns the placeholder
    # (200 PNG) so the map never shows broken images off-grid.
    r = client.get("/api/basemap/12/2223/1439.png?offline=true")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-tile-cache"] == "miss"
    assert r.content[:4] == b"\x89PNG"


def test_bad_tile_coords_rejected():
    assert client.get("/api/basemap/99/0/0.png").status_code == 400
    assert client.get("/api/basemap/10/-1/0.png?offline=true").status_code == 400


def test_status_endpoint():
    r = client.get("/api/basemap/status")
    assert r.status_code == 200
    body = r.json()
    assert {"tiles", "bytes", "mb"} <= set(body)
    assert isinstance(body["tiles"], int)


def test_download_tile_math():
    # A known lat/lon maps to a stable XYZ tile at a given zoom.
    x, y = deg2tile(0.0, 0.0, 1)          # equator/prime-meridian corner
    assert (x, y) == (1, 1)
    x, y = deg2tile(47.07, 15.44, 12)     # Graz
    assert x == 2223 and y == 1439
    # A small bbox yields a small, correctly-ordered tile range.
    xs, ys = tile_range(46.9, 15.2, 47.2, 15.6, 10)
    xs, ys = list(xs), list(ys)
    assert len(xs) >= 1 and len(ys) >= 1
    assert xs == sorted(xs) and ys == sorted(ys)
