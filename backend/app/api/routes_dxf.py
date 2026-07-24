"""DXF upload, layer inspection, georeferencing and overlay endpoints."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..config import MAX_DXF_BYTES
from ..services.saas.tiers import require_feature
from .routes_auth import current_user
from ..services.dxf import parser
from ..services.dxf.georef import build_georef
from ..services.dxf.gridder import build_grid
from ..services.dxf.overlay import footprint_lonlat, hillshade_png
from ..services.dxf.store import get_dxf_store

router = APIRouter(prefix="/api/dxf", tags=["dxf"])


# ---------------------------------------------------------------- schemas
class ControlPointIn(BaseModel):
    dxf_x: float
    dxf_y: float
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class GeorefRequest(BaseModel):
    mode: Literal["known_crs", "control_points", "origin_bearing"]
    layers: list[str] | None = None          # None = all layers
    # mode A
    crs: str | None = None                    # e.g. "EPSG:32633" or "EPSG:2154"
    # mode B
    control_points: list[ControlPointIn] | None = None
    # mode C
    origin_lat: float | None = None
    origin_lon: float | None = None
    bearing_deg: float = 0.0
    unit_scale: float = 1.0                   # meters per DXF unit (0.3048 = feet)
    origin_x: float = 0.0
    origin_y: float = 0.0
    # vertical unit scale for all modes (meters per DXF Z unit)
    z_scale: float | None = None


# ---------------------------------------------------------------- endpoints
@router.post("/upload")
async def upload_dxf(file: UploadFile = File(...),
                     user: dict | None = Depends(current_user)) -> dict:
    """Store the DXF and return its id + full layer inventory.
    Authenticated uploads are bound to the uploader: only the owner may
    re-georeference or delete them."""
    if not (file.filename or "").lower().endswith(".dxf"):
        raise HTTPException(400, "Only .dxf files are accepted")
    content = await file.read()
    if len(content) > MAX_DXF_BYTES:
        raise HTTPException(413, f"DXF exceeds the {MAX_DXF_BYTES // (1024*1024)} MB upload limit")

    session = get_dxf_store().create(file.filename or "upload.dxf", content,
                                     owner_id=user["id"] if user else None)
    try:
        doc = session.document()
    except Exception as exc:  # noqa: BLE001 - surface parse errors to the client
        get_dxf_store().delete(session.dxf_id)
        raise HTTPException(422, f"Could not parse DXF: {exc}") from exc

    session.layers = parser.list_layers(doc)
    return {"dxf_id": session.dxf_id, "filename": session.filename,
            "layers": session.layers,
            "georef_hints": _georef_hints(doc)}


def _georef_hints(doc) -> dict:
    """Frictionless onboarding: guess the likely georeferencing mode and
    unit from raw coordinate magnitudes so the wizard can pre-select
    sensible defaults instead of making the user diagnose them."""
    pts = parser.extract_points(doc, None)
    if pts.shape[0] < 3:
        return {"suggested_mode": "origin_bearing", "suggested_unit": "m",
                "reason": "too few points to analyze"}
    x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
    hints: dict = {}
    # Projected-CRS signature: UTM-like eastings/northings.
    if (100_000 <= abs(float(x.mean())) <= 900_000
            and 1_000_000 <= abs(float(y.mean())) <= 10_000_000):
        hints["suggested_mode"] = "known_crs"
        hints["reason"] = ("coordinate magnitudes look like projected "
                          "easting/northing (UTM-like) - pick the site's EPSG code")
    else:
        hints["suggested_mode"] = "origin_bearing"
        hints["reason"] = "small local coordinates - anchor an origin point"
    # Unit heuristic from plausible terrain elevations: Z above ~4,500 with
    # nothing above 30,000 smells like feet (14,764 ft = 4,500 m).
    z_valid = z[(z > 0) & (z < 30_000)]
    if z_valid.size and float(z_valid.mean()) > 4_500:
        hints["suggested_unit"] = "ft"
        hints["suggested_unit_scale"] = 0.3048
    else:
        hints["suggested_unit"] = "m"
        hints["suggested_unit_scale"] = 1.0
    return hints


@router.get("/{dxf_id}/layers")
def get_layers(dxf_id: str,
               user: dict | None = Depends(current_user)) -> dict:
    """All layers in the DXF, with point counts and Z ranges, so the user can
    choose which layers carry terrain data."""
    # Owner-scope the read (no tier gate: layer inspection precedes
    # georeferencing). Anonymous uploads stay open in self-hosted mode.
    session = resolve_dxf(dxf_id, user, gate=False, require_ready=False)
    if not session.layers:
        session.layers = parser.list_layers(session.document())
    return {"dxf_id": dxf_id, "layers": session.layers}


@router.post("/{dxf_id}/georeference")
def georeference(dxf_id: str, req: GeorefRequest,
                 user: dict | None = Depends(current_user)) -> dict:
    """Apply one of the three georeferencing modes, build the terrain grid,
    and run the SRTM cross-validation."""
    require_feature(user, "dxf_fusion")   # Pro-tier capability in SaaS mode
    session = _session_or_404(dxf_id)
    _check_owner(session, user)           # only the uploader may mutate

    # 1) Build the coordinate transform for the requested mode.
    params = req.model_dump(exclude_none=True)
    try:
        georef = build_georef(params)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, f"Invalid georeferencing parameters: {exc}") from exc

    # 2) Extract the scattered point cloud from the selected layers.
    points = parser.extract_points(session.document(), req.layers)
    if points.shape[0] < 3:
        raise HTTPException(422,
                            "The selected layers contain fewer than 3 elevation points; "
                            "select layers that carry terrain data (points, contours, "
                            "3D faces, meshes or spot heights).")

    # 3) Interpolate to a regular grid (Z converted to meters via z_scale).
    try:
        grid = build_grid(points, z_scale=georef.z_scale)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    # 4) Validate against the SRTM base over the same footprint (reuse the
    #    process-wide service so the DEM caches are shared).
    from .routes_terrain import get_fusion_service
    fusion = get_fusion_service()
    try:
        validation = fusion.validate_against_srtm(grid, georef)
    except Exception as exc:  # DEM download failure must not kill georeferencing
        validation = {"warning": None, "error": f"SRTM validation unavailable: {exc}"}

    # 5) Persist on the session (and to disk so other workers / a restarted
    #    server can rebuild the grid deterministically) + map artifacts.
    session.georef = georef
    session.grid = grid
    session.selected_layers = req.layers
    session.georef_params = params
    session.validation = validation
    session.footprint = footprint_lonlat(grid, georef)
    session.overlay_png, session.overlay_bounds = hillshade_png(grid, georef)
    session.persist_state()

    return {
        "dxf_id": dxf_id,
        "transform": georef.describe(),
        "grid": {"nx": grid.nx, "ny": grid.ny,
                 "cell_size_m": grid.dx * georef.meters_per_unit(),
                 "points_used": int(points.shape[0])},
        "footprint": session.footprint,
        "overlay_bounds": session.overlay_bounds,
        "overlay_url": f"/api/dxf/{dxf_id}/overlay.png",
        "validation": validation,
    }


@router.get("/{dxf_id}/overlay.png")
def overlay_png(dxf_id: str,
                alpha: float = Query(0.62, ge=0.0, le=1.0),
                user: dict | None = Depends(current_user)) -> Response:
    """Semi-transparent hillshade of the georeferenced DXF terrain."""
    # Owner-scoped read (gate=False keeps overlay reload working for the
    # anonymous self-hosted frontend); require_ready gives the 409 below.
    session = resolve_dxf(dxf_id, user, gate=False, require_ready=True)
    if alpha != 0.62:
        # Custom alpha renders are NOT cached - caching them would poison
        # the default-alpha response for every later caller.
        png, _bounds = hillshade_png(session.grid, session.georef, alpha=alpha)
        return Response(content=png, media_type="image/png",
                        headers={"Cache-Control": "no-cache"})
    if session.overlay_png is None:
        session.overlay_png, session.overlay_bounds = hillshade_png(
            session.grid, session.georef)
    return Response(content=session.overlay_png, media_type="image/png",
                    headers={"Cache-Control": "no-cache"})


@router.delete("/{dxf_id}")
def delete_dxf(dxf_id: str, user: dict | None = Depends(current_user)) -> dict:
    session = get_dxf_store().get(dxf_id)
    if session is not None:
        _check_owner(session, user)
    get_dxf_store().delete(dxf_id)
    return {"deleted": dxf_id}


def _session_or_404(dxf_id: str):
    session = get_dxf_store().get(dxf_id)
    if session is None:
        raise HTTPException(404, f"Unknown DXF id: {dxf_id}")
    return session


def _check_owner(session, user: dict | None) -> None:
    """Mutations on an owned DXF require the owning account; anonymous
    uploads stay open (self-hosted mode)."""
    if session.owner_id is not None and (
            user is None or user["id"] != session.owner_id):
        raise HTTPException(403, "This DXF belongs to another account")


def resolve_dxf(dxf_id: str, user: dict | None, *, gate: bool = True,
                require_ready: bool = True):
    """Shared access guard for every endpoint that CONSUMES a DXF by id.

    Enforces, in order: existence (404), cross-tenant ownership (403), the
    Pro ``dxf_fusion`` entitlement (402 in SaaS mode) and — by default —
    that the DXF has been georeferenced (409).  Returns the session so the
    caller can read ``session.grid`` / ``session.georef``.  Centralizing
    this closes the IDOR/tier-bypass class where read paths skipped the
    checks the mutation paths applied.
    """
    from ..services.saas.tiers import require_feature
    session = _session_or_404(dxf_id)
    _check_owner(session, user)
    if gate:
        require_feature(user, "dxf_fusion")
    if require_ready and not session.ensure_ready():
        raise HTTPException(409, "DXF has not been georeferenced yet")
    return session


@router.get("/{dxf_id}/state")
def dxf_state(dxf_id: str,
              user: dict | None = Depends(current_user)) -> dict:
    """Restore a previously georeferenced DXF (e.g. after a page reload):
    returns the same payload shape as POST /georeference."""
    # Owner-scoped read; gate=False so the anonymous frontend can restore its
    # own session, require_ready gives the 409 for not-yet-georeferenced DXFs.
    session = resolve_dxf(dxf_id, user, gate=False, require_ready=True)
    if session.footprint is None:
        session.footprint = footprint_lonlat(session.grid, session.georef)
    if session.overlay_bounds is None or session.overlay_png is None:
        session.overlay_png, session.overlay_bounds = hillshade_png(
            session.grid, session.georef)
    return {
        "dxf_id": dxf_id,
        "transform": session.georef.describe(),
        "grid": {"nx": session.grid.nx, "ny": session.grid.ny,
                 "cell_size_m": session.grid.dx * session.georef.meters_per_unit(),
                 "points_used": 0},
        "footprint": session.footprint,
        "overlay_bounds": session.overlay_bounds,
        "overlay_url": f"/api/dxf/{dxf_id}/overlay.png",
        "validation": session.validation or {"warning": None},
    }
