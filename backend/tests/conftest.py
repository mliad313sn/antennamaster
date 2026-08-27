"""Shared fixtures: a synthetic DXF site and an offline fake DEM store."""
from __future__ import annotations

import math
from pathlib import Path

import ezdxf
import numpy as np
import pytest

from tools._ramp_terrain import RampTileStore


class FakeTileStore(RampTileStore):
    """The shared synthetic-ramp DEM (tools/_ramp_terrain.py) + a fetch
    counter, so tests, the replay harness and the pipeline-proof generator
    all see the identical offline world."""

    def __init__(self, tmp_path: Path):
        super().__init__(cache_dir=tmp_path)
        self.fetch_count = 0

    def get_tile(self, z, x, y):
        key = (z, x % (2 ** z), y)
        with self._lock:
            cached = key in self._mem
        if not cached:
            self.fetch_count += 1
        return super().get_tile(z, x, y)


@pytest.fixture(autouse=True)
def _clean_telemetry():
    """Start every test with an empty live twin.

    Telemetry state is now shared through SQLite so sibling uvicorn workers
    see the same fleet, which also means it outlives a test - and a test that
    inherits another's assets fails in a place that has nothing to do with it.
    """
    from app.services import telemetry_store
    telemetry_store.reset()
    yield
    telemetry_store.reset()


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """The abuse limits are off by default in the suite.

    They are keyed by client IP, and every TestClient request comes from the
    same one, so a test that legitimately runs 30 coverage studies would trip
    a guard aimed at a runaway loop. `test_rate_limits.py` turns them back on
    for itself, which is where the behaviour belongs anyway.
    """
    monkeypatch.setenv("AM_RATE_LIMIT", "0")


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
