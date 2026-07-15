"""Local base-map tile server endpoints (offline resilience)."""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from ..services import basemap

router = APIRouter(prefix="/api/basemap", tags=["basemap"])


@router.get("/status")
def basemap_status() -> dict:
    """How many visual base-map tiles are cached locally (offline coverage)."""
    return basemap.cache_stats()


@router.get("/{z}/{x}/{y}.png")
def basemap_tile(z: int, x: int, y: int,
                 offline: bool = Query(False)) -> Response:
    """A Web-Mercator XYZ base-map tile from the local cache.

    Cache-first: served from disk if present, else fetched + cached from the
    upstream OSM source when online.  ``offline=true`` forces disk-only (used
    by the frontend when the browser reports no connectivity) and returns a
    neutral placeholder for any gap so the map never shows broken tiles.
    """
    if not (0 <= z <= 22) or x < 0 or y < 0:
        return JSONResponse({"detail": "bad tile coordinates"}, status_code=400)
    data, cached = basemap.fetch_tile(z, x, y, allow_network=not offline)
    return Response(
        content=data, media_type="image/png",
        headers={"Cache-Control": "public, max-age=604800",
                 "X-Tile-Cache": "hit" if cached else "miss"})
