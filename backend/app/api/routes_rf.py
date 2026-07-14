"""RF study endpoints: technology presets, propagation models, area coverage."""
from __future__ import annotations

import threading
from collections import OrderedDict

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..services.dxf.store import get_dxf_store
from ..services.rf.models import MODEL_INFO
from ..services.rf.technologies import TECHNOLOGIES, get_technology
from ..services.terrain.coverage import CoverageEngine, CoverageResult
from .routes_terrain import get_fusion_service

router = APIRouter(prefix="/api/rf", tags=["rf"])

# Completed coverage rasters kept for map display (bounded LRU).
_coverage_results: OrderedDict[str, CoverageResult] = OrderedDict()
_coverage_lock = threading.Lock()
_MAX_KEPT = 20


class CoverageRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    technology: str = "custom"
    radius_km: float = Field(10.0, gt=0.1, le=150.0)
    dxf_id: str | None = None
    # Optional overrides of the technology preset:
    freq_mhz: float | None = Field(None, gt=0)
    model: str | None = None
    environment: str | None = None
    tx_power_dbm: float | None = None
    tx_gain_dbi: float | None = None
    rx_gain_dbi: float | None = None
    losses_db: float | None = None
    rx_sensitivity_dbm: float | None = None
    h_bs_m: float | None = Field(None, gt=0)
    h_ut_m: float | None = Field(None, gt=0)
    # Sector antenna (omni when azimuth is null):
    antenna_azimuth_deg: float | None = Field(None, ge=0, lt=360)
    antenna_beamwidth_deg: float = Field(65.0, gt=5, le=360)
    # Simulation resolution:
    n_radials: int = Field(180, ge=36, le=720)
    n_steps: int = Field(100, ge=20, le=400)


@router.get("/technologies")
def list_technologies() -> dict:
    """All radio-study presets (2G/3G/4G/5G, PMR, broadcast, WLAN, IoT, PtP)."""
    return {"technologies": [{"key": k, **v} for k, v in TECHNOLOGIES.items()]}


@router.get("/models")
def list_models() -> dict:
    """All propagation models with validity ranges."""
    return {"models": [{"key": k, **v} for k, v in MODEL_INFO.items()]}


def _resolve_tech(req: CoverageRequest) -> dict:
    try:
        tech = get_technology(req.technology)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for f in ("freq_mhz", "model", "environment", "tx_power_dbm", "tx_gain_dbi",
              "rx_gain_dbi", "losses_db", "rx_sensitivity_dbm", "h_bs_m", "h_ut_m"):
        v = getattr(req, f)
        if v is not None:
            tech[f] = v
    if tech["model"] not in MODEL_INFO:
        raise HTTPException(422, f"Unknown propagation model: {tech['model']!r}")
    return tech


@router.post("/coverage")
def simulate_coverage(req: CoverageRequest) -> dict:
    """Run an area coverage simulation from a TX site over the fused terrain."""
    tech = _resolve_tech(req)

    grid = georef = None
    if req.dxf_id:
        session = get_dxf_store().get(req.dxf_id)
        if session is None:
            raise HTTPException(404, f"Unknown DXF id: {req.dxf_id}")
        if session.grid is None:
            raise HTTPException(409, "DXF has not been georeferenced yet")
        grid, georef = session.grid, session.georef

    engine = CoverageEngine(get_fusion_service())
    try:
        result = engine.simulate(
            req.lat, req.lon, tech, radius_m=req.radius_km * 1000.0,
            n_radials=req.n_radials, n_steps=req.n_steps,
            antenna_azimuth_deg=req.antenna_azimuth_deg,
            antenna_beamwidth_deg=req.antenna_beamwidth_deg,
            grid=grid, georef=georef,
        )
    except Exception as exc:  # DEM fetch failure -> 502, not a stacktrace
        raise HTTPException(502, f"Coverage simulation failed: {exc}") from exc

    with _coverage_lock:
        _coverage_results[result.coverage_id] = result
        while len(_coverage_results) > _MAX_KEPT:
            _coverage_results.popitem(last=False)

    return {
        "coverage_id": result.coverage_id,
        "png_url": f"/api/rf/coverage/{result.coverage_id}.png",
        "bounds": result.bounds,
        "legend": result.legend,
        "stats": result.stats,
        "technology": {**tech, "key": req.technology},
        "warnings": result.warnings,
    }


@router.get("/coverage/{coverage_id}.png")
def coverage_png(coverage_id: str) -> Response:
    with _coverage_lock:
        result = _coverage_results.get(coverage_id)
    if result is None:
        raise HTTPException(404, "Coverage result expired or unknown")
    return Response(content=result.png, media_type="image/png",
                    headers={"Cache-Control": "max-age=3600"})
