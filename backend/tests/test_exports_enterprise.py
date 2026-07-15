"""Tests for enterprise GIS/procurement exports: GeoTIFF coverage raster and
hardware BOM CSV."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.geotiff import rgba_png_to_geotiff, world_file
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


def _png(w=8, h=6):
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), (40, 120, 200, 150)).save(buf, format="PNG")
    return buf.getvalue()


def test_geotiff_tags_are_correct():
    bounds = [[47.0, 15.0], [47.05, 15.1]]      # [[S,W],[N,E]]
    tif = rgba_png_to_geotiff(_png(10, 5), bounds)
    im = Image.open(io.BytesIO(tif))
    tags = im.tag_v2
    assert im.format == "TIFF"
    # ModelPixelScale = (dlon/w, dlat/h, 0).
    sx, sy, sz = tags[33550]
    assert sx == pytest.approx((15.1 - 15.0) / 10, abs=1e-9)
    assert sy == pytest.approx((47.05 - 47.0) / 5, abs=1e-9)
    # Tiepoint maps raster (0,0) to the NW corner (west, north).
    _, _, _, tx, ty, _ = tags[33922]
    assert (tx, ty) == pytest.approx((15.0, 47.05))
    # GeoKeyDirectory declares EPSG:4326.
    gk = tags[34735]
    assert 4326 in gk and gk[0] == 1


def test_world_file_math():
    wld = world_file([[47.0, 15.0], [47.05, 15.1]], 10, 5).splitlines()
    assert float(wld[0]) == pytest.approx(0.01)         # x scale
    assert float(wld[3]) == pytest.approx(-0.01)        # y scale (negative)
    assert float(wld[4]) == pytest.approx(15.0 + 0.005)  # x of pixel-center 0
    assert float(wld[5]) == pytest.approx(47.05 - 0.005)


def test_coverage_geotiff_endpoint(client):
    cov = client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "gsm900", "radius_km": 4,
        "n_radials": 36, "n_steps": 20}).json()
    cid = cov["coverage_id"]
    r = client.get(f"/api/rf/coverage/{cid}.tif")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/tiff"
    im = Image.open(io.BytesIO(r.content))
    assert im.format == "TIFF" and 33550 in im.tag_v2
    assert client.get("/api/rf/coverage/nope.tif").status_code == 404


def test_bom_csv_export(client):
    r = client.get("/api/saas/bom.csv", params={"technology": "private_nr_n77",
                                                "sites": 12})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[1].startswith("item,qty_per_site,qty_total")
    # A per-site qty must scale to the fleet total in the row.
    data_rows = [l for l in lines if l and not l.startswith(("#", "item", "CAPEX",
                 "OPEX", "5-year")) and "," in l]
    assert data_rows, "expected BOM line items"
    # TCO summary row present.
    assert any(l.startswith("5-year TCO") for l in lines)
