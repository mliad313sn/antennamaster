"""Per-pixel clutter endpoints: WorldCover status + building-footprint import."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .routes_auth import current_user
from .routes_terrain import resolve_fusion

router = APIRouter(prefix="/api/clutter", tags=["clutter"])


@router.get("/status")
def clutter_status() -> dict:
    """WorldCover clutter source: class table, cache state, data licence."""
    from ..services.clutter.worldcover import CLASS_TABLE, get_worldcover_store
    store = get_worldcover_store()
    cache_dir = getattr(store, "cache_dir", None)
    cached = list(cache_dir.glob("*.npz")) if cache_dir else []
    return {
        "source": "ESA WorldCover 10 m v200 (2021)",
        "licence": "CC-BY 4.0 — free, global",
        "url_template": getattr(store, "url_template", None),
        "classes": [{"code": k, "label": l, "height_m": h}
                    for k, (l, h) in CLASS_TABLE.items()],
        "cache": {"windows": len(cached),
                  "bytes": sum(p.stat().st_size for p in cached)},
    }


class BuildingsImport(BaseModel):
    geojson: dict
    cell_m: float = Field(2.0, ge=0.5, le=20)
    default_height_m: float = Field(9.0, ge=1, le=200)


@router.post("/buildings")
def import_buildings(req: BuildingsImport,
                     user: dict | None = Depends(current_user)) -> dict:
    """Extrude GeoJSON building footprints (Overture / OSM export) into a
    surface-model overlay; the returned ``dsm_id`` plugs into every
    surface-aware study (e.g. /api/lidar/{id}/profile diffraction)."""
    from ..services.clutter.buildings import buildings_to_dsm
    from ..services.lidar.store import STORE
    fusion = resolve_fusion(False)
    try:
        grid, georef, stats = buildings_to_dsm(
            req.geojson, fusion, cell_m=req.cell_m,
            default_height_m=req.default_height_m)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Building import failed: {exc}") from exc
    sess = STORE.add(grid, georef, stats)
    return {"dsm_id": sess.dsm_id, "stats": stats, "bounds": sess.bounds_lonlat}
