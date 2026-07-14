"""Global base-elevation engine backed by Mapzen Terrarium RGB tiles.

Terrarium tiles encode elevation in the RGB channels of a 256x256 PNG:

    elevation_m = (R * 256 + G + B / 256) - 32768

Tiles follow the standard Web-Mercator Z/X/Y scheme.  Every fetched tile is
cached on disk (keyed by Z/X/Y) and in memory (decoded numpy array), so a
tile is downloaded at most once per install and decoded at most once per
process lifetime.
"""
from __future__ import annotations

import io
import threading
from collections import OrderedDict
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

from ...config import (DEM_CACHE_BUDGET_MB, DEM_CACHE_DIR, DEM_ZOOM,
                       TERRARIUM_URL)

TILE_SIZE = 256


def lonlat_to_global_px(lon, lat, zoom: int):
    """Project WGS84 lon/lat (scalars or arrays) to continuous global pixel
    coordinates at `zoom`.  Fully vectorized - coverage fans sample hundreds
    of thousands of points per request."""
    # Web-Mercator clamps latitude; Terrarium has no data beyond ~85 deg anyway.
    lat = np.clip(np.asarray(lat, dtype=np.float64), -85.05112878, 85.05112878)
    lon = np.asarray(lon, dtype=np.float64)
    n = TILE_SIZE * (2 ** zoom)
    x = (lon + 180.0) / 360.0 * n
    siny = np.sin(np.radians(lat))
    y = (0.5 - np.log((1 + siny) / (1 - siny)) / (4 * np.pi)) * n
    return x, y


class TerrariumTileStore:
    """Fetch, disk-cache and decode Terrarium elevation tiles."""

    def __init__(self, cache_dir: Path = DEM_CACHE_DIR, url_template: str = TERRARIUM_URL,
                 zoom: int = DEM_ZOOM):
        self.cache_dir = Path(cache_dir)
        self.url_template = url_template
        self.zoom = zoom
        # Bounded decoded-tile cache (LRU): ~256 KB per tile, 2000 tiles
        # ~= 500 MB worst case per process instead of unbounded growth.
        self._mem: "OrderedDict[tuple[int, int, int], np.ndarray]" = OrderedDict()
        self._mem_cap = 2000
        self._downloads = 0
        self._lock = threading.Lock()
        self._client = httpx.Client(timeout=30.0, follow_redirects=True)

    # ------------------------------------------------------------------ tiles
    def _tile_path(self, z: int, x: int, y: int) -> Path:
        return self.cache_dir / str(z) / str(x) / f"{y}.png"

    def _fetch_tile_bytes(self, z: int, x: int, y: int) -> bytes:
        """Return raw PNG bytes, downloading only on a disk-cache miss."""
        path = self._tile_path(z, x, y)
        if path.exists():
            return path.read_bytes()
        resp = self._client.get(self.url_template.format(z=z, x=x, y=y))
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write via a temp file so a crashed download never poisons the cache.
        tmp = path.with_suffix(".part")
        tmp.write_bytes(resp.content)
        tmp.replace(path)
        # Every 100 downloads, sweep the disk cache back under its budget so
        # long-running installs cannot fill the data volume.
        self._downloads += 1
        if self._downloads % 100 == 0:
            self.evict_disk_cache()
        return resp.content

    def evict_disk_cache(self, budget_mb: int = DEM_CACHE_BUDGET_MB) -> int:
        """Delete oldest tiles (by mtime) until the cache fits the budget.
        Returns the number of tiles removed."""
        tiles = sorted(self.cache_dir.glob("*/*/*.png"),
                       key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in tiles)
        removed = 0
        budget = budget_mb * 1024 * 1024
        for p in tiles:
            if total <= budget:
                break
            total -= p.stat().st_size
            p.unlink(missing_ok=True)
            removed += 1
        return removed

    def get_tile(self, z: int, x: int, y: int) -> np.ndarray:
        """Return the decoded elevation array (256x256 float32, meters)."""
        # Tiles wrap in X (antimeridian); clamp Y at the poles.
        x = x % (2 ** z)
        y = min(max(y, 0), 2 ** z - 1)
        key = (z, x, y)
        with self._lock:
            cached = self._mem.get(key)
            if cached is not None:
                self._mem.move_to_end(key)
                return cached
        raw = self._fetch_tile_bytes(z, x, y)
        rgb = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"), dtype=np.float64)
        elev = (rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0) - 32768.0
        elev = elev.astype(np.float32)
        with self._lock:
            self._mem[key] = elev
            while len(self._mem) > self._mem_cap:
                self._mem.popitem(last=False)
        return elev

    # ------------------------------------------------------------- elevation
    def elevations(self, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
        """Bilinearly-interpolated elevations (meters) for arrays of lon/lat.

        Sampling works in continuous global pixel space so interpolation is
        seamless across tile boundaries: the four neighbouring pixels of each
        query point are gathered from whichever tiles contain them.
        """
        lons = np.asarray(lons, dtype=np.float64)
        lats = np.asarray(lats, dtype=np.float64)
        z = self.zoom
        n_px = TILE_SIZE * (2 ** z)

        gx, gy = lonlat_to_global_px(lons, lats, z)

        # Pixel centers sit at +0.5; shift so integer indices are pixel centers.
        fx = gx - 0.5
        fy = gy - 0.5
        x0 = np.floor(fx).astype(np.int64)
        y0 = np.floor(fy).astype(np.int64)
        wx = fx - x0
        wy = fy - y0

        out = np.zeros(lons.shape, dtype=np.float64)
        # Accumulate the four bilinear corners.
        for dx, dy, w in (
            (0, 0, (1 - wx) * (1 - wy)),
            (1, 0, wx * (1 - wy)),
            (0, 1, (1 - wx) * wy),
            (1, 1, wx * wy),
        ):
            px = (x0 + dx) % n_px            # wrap around the antimeridian
            py = np.clip(y0 + dy, 0, n_px - 1)
            tx, ty = px // TILE_SIZE, py // TILE_SIZE
            ix, iy = px % TILE_SIZE, py % TILE_SIZE
            vals = np.empty(lons.shape, dtype=np.float64)
            # Group queries by tile so each tile is decoded/fetched once.
            flat_t = np.stack([tx.ravel(), ty.ravel()], axis=1)
            for tile_xy in {tuple(t) for t in flat_t}:
                mask = (tx == tile_xy[0]) & (ty == tile_xy[1])
                tile = self.get_tile(z, int(tile_xy[0]), int(tile_xy[1]))
                vals[mask] = tile[iy[mask], ix[mask]]
            out += w * vals
        return out

    def elevation_at(self, lon: float, lat: float) -> float:
        return float(self.elevations(np.array([lon]), np.array([lat]))[0])


# Process-wide singleton store (the FastAPI app and services share the cache).
_store: TerrariumTileStore | None = None
_store_lock = threading.Lock()


def get_tile_store() -> TerrariumTileStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = TerrariumTileStore()
        return _store
