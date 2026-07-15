"""Local visual base-map tile server — true offline resilience.

Serves standard OSM raster tiles from an on-disk cache under
``BASEMAP_CACHE_DIR``.  When online, a cache miss is fetched from
``BASEMAP_URL`` and stored (so browsing warms the cache); the
``download_basemap`` utility can pre-fetch a whole bounding box for a site
that will go offline.  When offline and a tile isn't cached, a neutral
placeholder tile is returned so the map still renders instead of showing
broken images — the "seamless fallback" the field UI relies on.

Tile numbering is the standard Web-Mercator XYZ scheme (EPSG:3857), the same
Leaflet uses, so cached tiles line up exactly with the online layers.
"""
from __future__ import annotations

import io
import threading

import httpx
from PIL import Image

from ..config import BASEMAP_CACHE_DIR, BASEMAP_URL

# A polite, identifiable UA is required by the OSM tile usage policy.
_UA = "AntennaMaster/2 (+offline basemap cache; RF coverage simulator)"
_client = httpx.Client(timeout=15.0, follow_redirects=True,
                       headers={"User-Agent": _UA})
_lock = threading.Lock()
_placeholder: bytes | None = None


def _tile_path(z: int, x: int, y: int):
    return BASEMAP_CACHE_DIR / str(z) / str(x) / f"{y}.png"


def placeholder_tile() -> bytes:
    """A neutral 256×256 tile shown when a tile is neither cached nor
    reachable (offline gap).  Rendered once and reused."""
    global _placeholder
    if _placeholder is None:
        img = Image.new("RGB", (256, 256), (232, 234, 238))
        # Faint grid so the map reads as "no data here" rather than blank.
        px = img.load()
        for i in range(0, 256, 32):
            for j in range(256):
                px[i, j] = (214, 217, 223)
                px[j, i] = (214, 217, 223)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        _placeholder = buf.getvalue()
    return _placeholder


def fetch_tile(z: int, x: int, y: int, allow_network: bool = True
               ) -> tuple[bytes, bool]:
    """Return (png_bytes, from_cache).  Serves the cached tile if present;
    otherwise fetches + caches it when online.  Never raises — on an offline
    miss it returns the placeholder so the map keeps rendering."""
    path = _tile_path(z, x, y)
    if path.exists():
        try:
            return path.read_bytes(), True
        except OSError:
            pass
    if not allow_network:
        return placeholder_tile(), False
    url = BASEMAP_URL.format(z=z, x=x, y=y)
    try:
        resp = _client.get(url)
        resp.raise_for_status()
        data = resp.content
    except Exception:
        # Offline or upstream error: degrade gracefully.
        return placeholder_tile(), False
    # Cache atomically.
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    except OSError:
        pass
    return data, False


def cache_stats() -> dict:
    """Count and byte-size of the cached base-map tiles (for the UI/status)."""
    n = 0
    total = 0
    for p in BASEMAP_CACHE_DIR.glob("*/*/*.png"):
        try:
            total += p.stat().st_size
            n += 1
        except OSError:
            continue
    return {"tiles": n, "bytes": total, "mb": round(total / 1e6, 1)}
