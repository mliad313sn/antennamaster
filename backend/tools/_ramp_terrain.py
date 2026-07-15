"""Deterministic synthetic DEM used by the pipeline-proof datasets and tests.

A gentle east-west ramp — elevation = 100 + 500 · (global pixel column / world
width) — smooth, seed-free, and network-free, while exercising the exact same
tile/bilinear sampling code paths as production.  ``tests/conftest.py`` builds
its FakeTileStore on this class so the generator, the replay harness and the
test suite all see the *identical* world.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from app.services.dem.tiles import TerrariumTileStore


class RampTileStore(TerrariumTileStore):
    """DEM store that synthesizes ramp tiles instead of downloading them."""

    def __init__(self, cache_dir: Path, zoom: int = 12):
        super().__init__(cache_dir=Path(cache_dir) / "dem", zoom=zoom)

    def _fetch_tile_bytes(self, z, x, y):  # pragma: no cover — never called
        raise AssertionError("network fetch attempted on synthetic terrain")

    def get_tile(self, z, x, y):
        key = (z, x % (2 ** z), y)
        with self._lock:
            if key in self._mem:
                return self._mem[key]
        n = 256 * (2 ** z)
        cols = (x * 256 + np.arange(256)) / n          # 0..1 across the world
        tile = np.tile(100.0 + 500.0 * cols, (256, 1)).astype(np.float32)
        with self._lock:
            self._mem[key] = tile
        return tile
