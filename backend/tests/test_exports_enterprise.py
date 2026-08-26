"""Tests for enterprise GIS/procurement exports: GeoTIFF coverage raster and
hardware BOM CSV."""
import io

import numpy as np

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.geotiff import (field_to_geotiff,
                                  rgba_png_to_geotiff, world_file)
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


# ------------------------------------------------- numeric (Float32) export
def test_float_geotiff_is_data_not_a_picture():
    """The coloured export is five 8-bit classes with alpha baked in: a GIS
    team cannot threshold it at their own -95 dBm, reclassify it or intersect
    it with a demand layer. The numeric field was already computed and stored
    and simply never exported. This is that export."""
    rasterio = pytest.importorskip("rasterio")
    grid = np.array([[-60.0, -70.5], [-80.25, np.nan]], dtype=np.float32)
    tif = field_to_geotiff(grid, [[46.0, 14.0], [47.0, 15.0]])

    with rasterio.io.MemoryFile(tif) as mem, mem.open() as ds:
        assert ds.count == 1                      # one band, not RGBA
        assert ds.dtypes[0] == "float32"          # values, not 0-255 classes
        assert ds.crs.to_epsg() == 4326
        assert np.isnan(ds.nodata)                # unserved reads as no-data
        w, s_, e, n = ds.bounds
        assert (round(w), round(s_), round(e), round(n)) == (14, 46, 15, 47)
        back = ds.read(1)
        # Physical values survive the round trip exactly.
        assert back[0, 0] == pytest.approx(-60.0)
        assert back[1, 0] == pytest.approx(-80.25)
        assert np.isnan(back[1, 1])


def test_coverage_geotiff_band_endpoint(client):
    rasterio = pytest.importorskip("rasterio")
    cid = client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "gsm900", "radius_km": 4,
        "n_radials": 36, "n_steps": 20, "raster_px": 128}).json()["coverage_id"]

    for band, lo, hi in (("rx_power", -250.0, 60.0), ("margin", -250.0, 250.0)):
        r = client.get(f"/api/rf/coverage/{cid}.tif", params={"band": band})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "image/tiff"
        with rasterio.io.MemoryFile(r.content) as mem, mem.open() as ds:
            assert ds.count == 1 and ds.dtypes[0] == "float32"
            a = ds.read(1)
            finite = a[np.isfinite(a)]
            assert finite.size > 0
            assert lo < float(finite.min()) and float(finite.max()) < hi
            # Beyond the study radius the disc is nodata, not a low signal.
            assert np.isnan(a).any()

    # The default is unchanged, so existing links and tools keep working.
    plain = client.get(f"/api/rf/coverage/{cid}.tif")
    assert plain.status_code == 200
    with rasterio.io.MemoryFile(plain.content) as mem, mem.open() as ds:
        assert ds.count == 4 and ds.dtypes[0] == "uint8"

    # An unknown band is refused rather than silently ignored.
    assert client.get(f"/api/rf/coverage/{cid}.tif",
                      params={"band": "nonsense"}).status_code == 422
