"""Shared fixtures: a synthetic DXF site and an offline fake DEM store."""
from __future__ import annotations

import math
from pathlib import Path

import ezdxf
import numpy as np
import pytest

from app.services.dem.tiles import TerrariumTileStore


class FakeTileStore(TerrariumTileStore):
    """DEM store that synthesizes tiles instead of downloading them.

    The fake world is a gentle east-west ramp: elevation = 100 + 500 * frac_x
    of the global pixel column, which is smooth, deterministic, and exercises
    the exact same bilinear/global-pixel sampling code paths as production.
    """

    def __init__(self, tmp_path: Path):
        super().__init__(cache_dir=tmp_path / "dem", zoom=12)
        self.fetch_count = 0

    def _fetch_tile_bytes(self, z, x, y):  # pragma: no cover - never called
        raise AssertionError("network fetch attempted in tests")

    def get_tile(self, z, x, y):
        key = (z, x % (2 ** z), y)
        with self._lock:
            if key in self._mem:
                return self._mem[key]
        self.fetch_count += 1
        n = 256 * (2 ** z)
        cols = (x * 256 + np.arange(256)) / n          # 0..1 across the world
        tile = np.tile(100.0 + 500.0 * cols, (256, 1)).astype(np.float32)
        with self._lock:
            self._mem[key] = tile
        return tile


@pytest.fixture
def fake_store(tmp_path):
    return FakeTileStore(tmp_path)


@pytest.fixture
def site_dxf(tmp_path) -> Path:
    """Synthetic survey DXF: a 1000x1000 m site in local coordinates.

    True surface: z = 200 + 0.05*x + 0.02*y (meters), sampled by POINTs,
    contour LWPOLYLINEs, one 3DFACE, one TEXT spot height, and a 3D POLYLINE,
    across two layers (plus a non-terrain layer with plain linework).
    """
    doc = ezdxf.new("R2010")
    for name in ("SURVEY_POINTS", "CONTOURS", "BUILDINGS"):
        doc.layers.add(name)
    msp = doc.modelspace()

    def z_of(x, y):
        return 200.0 + 0.05 * x + 0.02 * y

    # Survey POINTs on a 100 m grid.
    for x in range(0, 1001, 100):
        for y in range(0, 1001, 100):
            msp.add_point((x, y, z_of(x, y)), dxfattribs={"layer": "SURVEY_POINTS"})

    # Contour lines: LWPOLYLINEs at constant elevation (Z via `elevation`).
    for i, zc in enumerate((210.0, 230.0, 250.0)):
        pts = [(50 + 300 * i, 50 + 90 * j) for j in range(10)]
        msp.add_lwpolyline(pts, dxfattribs={"layer": "CONTOURS", "elevation": zc})

    # One 3DFACE patch and a 3D polyline ridge.
    msp.add_3dface([(0, 0, z_of(0, 0)), (100, 0, z_of(100, 0)),
                    (100, 100, z_of(100, 100)), (0, 100, z_of(0, 100))],
                   dxfattribs={"layer": "SURVEY_POINTS"})
    msp.add_polyline3d([(500, y, z_of(500, y)) for y in range(0, 1001, 250)],
                       dxfattribs={"layer": "SURVEY_POINTS"})

    # Spot height as TEXT at its insert point (off the survey grid).
    msp.add_text("245.5", dxfattribs={"layer": "SURVEY_POINTS",
                                      "insert": (905, 895)})

    # Non-terrain noise: building outline drawn with LINE entities, which
    # carry no terrain information and are ignored by the extractor.
    for a, b in (((10, 10), (20, 10)), ((20, 10), (20, 20)),
                 ((20, 20), (10, 20)), ((10, 20), (10, 10))):
        msp.add_line(a, b, dxfattribs={"layer": "BUILDINGS"})

    path = tmp_path / "site.dxf"
    doc.saveas(path)
    return path
