"""ESA WorldCover 10 m land cover as per-pixel RF clutter.

Replaces the *statistical* clutter guess (ITU-R P.2108) with the *actual* land
cover under the path: every profile/coverage sample is classified (tree cover,
built-up, cropland, water …) from the free, global ESA WorldCover 10 m map
(CC-BY 4.0, hosted as Cloud-Optimized GeoTIFFs on the AWS Open Data Registry),
and a representative clutter height per class is added to the terrain the
Deygout diffraction engine sees — real, localized obstacles instead of a
percentage curve.

Data access is COG-native: only the byte ranges covering the queried window are
fetched (HTTP range reads via rasterio/GDAL), cached on disk, and decimated to
a hard pixel cap for very long paths (nearest-neighbour, class-safe).  Fully
offline once cached; the store is pluggable so tests use a synthetic world.

Representative clutter heights follow the ITU-R P.1812 "representative clutter
height" practice (documented planning values, overridable via
``AM_CLUTTER_HEIGHTS`` JSON):

    10 tree cover 15 m · 20 shrubland 1.5 m · 30 grassland 0 · 40 cropland 1 m
    50 built-up 10 m · 60 bare 0 · 70 snow/ice 0 · 80 water 0
    90 herbaceous wetland 0 · 95 mangroves 10 m · 100 moss/lichen 0
"""
from __future__ import annotations

import json
import math
import os
import threading
from pathlib import Path

import numpy as np

from ...config import DATA_DIR

# WorldCover v200 (2021): 3°x3° COG tiles named by their SW corner.
DEFAULT_URL = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com"
               "/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif")

# class -> (label, representative clutter height in metres)
CLASS_TABLE: dict[int, tuple[str, float]] = {
    10: ("Tree cover", 15.0),
    20: ("Shrubland", 1.5),
    30: ("Grassland", 0.0),
    40: ("Cropland", 1.0),
    50: ("Built-up", 10.0),
    60: ("Bare / sparse", 0.0),
    70: ("Snow / ice", 0.0),
    80: ("Water", 0.0),
    90: ("Herbaceous wetland", 0.0),
    95: ("Mangroves", 10.0),
    100: ("Moss / lichen", 0.0),
}

# Hard cap on pixels fetched per window; long paths are decimated (nearest —
# classes stay valid, resolution degrades gracefully and is reported).
MAX_WINDOW_PX = 4_000_000


def _heights_table() -> dict[int, float]:
    table = {k: h for k, (_l, h) in CLASS_TABLE.items()}
    override = os.environ.get("AM_CLUTTER_HEIGHTS")
    if override:
        try:
            for k, v in json.loads(override).items():
                table[int(k)] = float(v)
        except (ValueError, TypeError):
            pass
    return table


def tile_name(lat: float, lon: float) -> str:
    """WorldCover tile id for a coordinate: SW corner on a 3-degree grid."""
    lat0 = int(math.floor(lat / 3.0) * 3)
    lon0 = int(math.floor(lon / 3.0) * 3)
    ns = "N" if lat0 >= 0 else "S"
    ew = "E" if lon0 >= 0 else "W"
    return f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}"


class WorldCoverStore:
    """Windowed, cached access to WorldCover classes at arbitrary lon/lat."""

    def __init__(self, url_template: str | None = None,
                 cache_dir: Path | None = None):
        self.url_template = url_template or os.environ.get(
            "AM_WORLDCOVER_URL", DEFAULT_URL)
        self.cache_dir = cache_dir or (DATA_DIR / "worldcover_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._mem: dict[str, tuple] = {}          # cache_key -> (arr, transform)
        self.heights_by_class = _heights_table()

    # -------------------------------------------------------------- fetching
    def _gdal_env(self) -> dict:
        env = {
            "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
            "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
            "GDAL_HTTP_TIMEOUT": "30",
            "GDAL_HTTP_MAX_RETRY": "3",
            "GDAL_HTTP_RETRY_DELAY": "1",
        }
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy:
            env["GDAL_HTTP_PROXY"] = proxy
        ca = os.environ.get("CURL_CA_BUNDLE") or "/root/.ccr/ca-bundle.crt"
        if Path(ca).exists():
            env["CURL_CA_BUNDLE"] = ca
        return env

    def _window_key(self, tile: str, w: float, s: float, e: float, n: float,
                    decim: int) -> str:
        q = 1e4  # quantize to ~11 m so nearby queries share a cache entry
        return (f"{tile}_{int(w*q)}_{int(s*q)}_{int(e*q)}_{int(n*q)}_d{decim}")

    def _read_window(self, tile: str, west: float, south: float,
                     east: float, north: float):
        """(class array, affine transform) for a bbox within one tile."""
        import rasterio
        from rasterio.windows import from_bounds

        url = self.url_template.format(tile=tile)
        with rasterio.Env(**self._gdal_env()):
            with rasterio.open(f"/vsicurl/{url}") as ds:
                win = from_bounds(west, south, east, north, ds.transform)
                px = max(int(win.width), 1) * max(int(win.height), 1)
                decim = max(1, int(math.ceil(math.sqrt(px / MAX_WINDOW_PX))))
                key = self._window_key(tile, west, south, east, north, decim)
                with self._lock:
                    if key in self._mem:
                        return self._mem[key]
                disk = self.cache_dir / f"{key}.npz"
                if disk.exists():
                    z = np.load(disk)
                    out = (z["arr"], tuple(z["transform"]))
                    with self._lock:
                        self._mem[key] = out
                    return out
                out_shape = (max(int(win.height) // decim, 1),
                             max(int(win.width) // decim, 1))
                arr = ds.read(1, window=win, out_shape=out_shape).astype(np.uint8)
                t = rasterio.windows.transform(win, ds.transform)
                # Adjust the transform for decimation.
                transform = (t.a * decim, t.b, t.c, t.d, t.e * decim, t.f)
                tmp = disk.with_suffix(".tmp.npz")
                np.savez_compressed(tmp, arr=arr, transform=np.array(transform))
                tmp.replace(disk)
                out = (arr, transform)
                with self._lock:
                    self._mem[key] = out
                return out

    # -------------------------------------------------------------- sampling
    def classes(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        """WorldCover class per point (uint8; 0 where unavailable)."""
        lats = np.asarray(lats, dtype=np.float64)
        lons = np.asarray(lons, dtype=np.float64)
        out = np.zeros(lats.shape, dtype=np.uint8)
        # Group by tile so one bbox window serves the whole group.
        tiles: dict[str, np.ndarray] = {}
        for i in range(lats.size):
            tiles.setdefault(tile_name(lats.flat[i], lons.flat[i]),
                             np.zeros(0, int))
        for tile in tiles:
            mask = np.fromiter(
                (tile_name(lats.flat[i], lons.flat[i]) == tile
                 for i in range(lats.size)), bool, lats.size)
            la, lo = lats.flat[mask], lons.flat[mask]
            pad = 2e-4  # ~20 m guard band
            arr, (a, _b, c, _d, e, f) = self._read_window(
                tile, lo.min() - pad, la.min() - pad,
                lo.max() + pad, la.max() + pad)
            cols = np.clip(((lo - c) / a).astype(int), 0, arr.shape[1] - 1)
            rows = np.clip(((la - f) / e).astype(int), 0, arr.shape[0] - 1)
            out.flat[np.where(mask)[0]] = arr[rows, cols]
        return out

    def heights(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        """Representative clutter height (m) per point."""
        cls = self.classes(lats, lons)
        h = np.zeros(cls.shape, dtype=np.float64)
        for code, height in self.heights_by_class.items():
            if height > 0:
                h[cls == code] = height
        return h


_STORE: WorldCoverStore | None = None
_STORE_LOCK = threading.Lock()


def get_worldcover_store() -> WorldCoverStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = WorldCoverStore()
        return _STORE


def clutter_profile_heights(store, lats: np.ndarray, lons: np.ndarray,
                            terminal_clear: int = 1) -> np.ndarray:
    """Clutter heights for a TX→RX profile, with the terminal samples zeroed.

    Standard practice (P.1812 terminal height-gain): the clutter at the
    terminals themselves is handled by antenna siting, not treated as a
    mid-path obstacle — otherwise a mast *in* a forest would block itself.
    """
    h = store.heights(lats, lons)
    n = h.shape[0] if h.ndim else 0
    tc = max(int(terminal_clear), 0)
    if n and tc:
        h[:min(tc, n)] = 0.0
        h[max(n - tc, 0):] = 0.0
    return h
