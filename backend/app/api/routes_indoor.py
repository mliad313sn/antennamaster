"""Indoor & underground study endpoints.

Reuses the DXF upload store: the same uploaded file can be treated as
terrain relief (georeferencing pipeline) or as a structural floor plan /
mine gallery layout (this module) — the user decides per study.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..services import results_store
from ..services.dxf.store import get_dxf_store
from ..services.indoor.engine import simulate_indoor
from ..services.indoor.floorplan import extract_walls, render_preview
from ..services.indoor.materials import guess_material, list_materials
from ..services.rf.technologies import get_technology
from ..services.rf.underground import (EARTH_PRESETS, TUNNEL_WALL_PRESETS,
                                       tte_link, tunnel_profile)

router = APIRouter(prefix="/api/indoor", tags=["indoor-underground"])


# ------------------------------------------------------------------ schemas
class IndoorCoverageRequest(BaseModel):
    dxf_id: str
    layer_materials: dict[str, str]      # layer name -> material key
    tx_x: float                          # TX position in DXF drawing units
    tx_y: float
    unit_scale: float = Field(1.0, gt=0)  # meters per drawing unit
    technology: str | None = None        # preset for link params (optional)
    freq_mhz: float | None = Field(None, gt=0)
    tx_power_dbm: float | None = None
    tx_gain_dbi: float | None = None
    rx_gain_dbi: float | None = None
    losses_db: float | None = None
    rx_sensitivity_dbm: float | None = None
    tx_height_m: float = Field(2.5, gt=0)
    rx_height_m: float = Field(1.2, gt=0)
    grid_px: int = Field(200, ge=50, le=400)


# ---------------------------------------------------------------- materials
@router.get("/materials")
def materials() -> dict:
    """Wall material attenuation library (dB per crossing, by frequency)."""
    return {"materials": list_materials()}


@router.get("/presets")
def underground_presets() -> dict:
    """Tunnel wall permittivity + earth conductivity presets."""
    return {
        "tunnel_walls": [{"key": k, **v} for k, v in TUNNEL_WALL_PRESETS.items()],
        "earth": [{"key": k, **v} for k, v in EARTH_PRESETS.items()],
    }


# ------------------------------------------------------------- floor plans
@router.get("/{dxf_id}/preview.png")
def floorplan_preview(dxf_id: str, layers: str = Query("")) -> Response:
    """Wall linework preview so the user can click a TX position.

    ``layers`` is a comma-separated list; empty = all layers.  The DXF-unit
    bounds of the image are returned in the X-Plan-Bounds header
    (``x0,y0,x1,y1``) for click-coordinate mapping.
    """
    session = _session_or_404(dxf_id)
    wanted = [l for l in layers.split(",") if l] or [
        l["name"] for l in (session.layers or [])]
    layer_materials = {name: guess_material(name) for name in wanted}
    walls = extract_walls(session.document(), layer_materials)
    if walls.count == 0:
        raise HTTPException(422, "No structural entities (LINE/POLYLINE/ARC) "
                                 "found on the selected layers")
    png, bounds = render_preview(walls)
    return Response(content=png, media_type="image/png",
                    headers={"X-Plan-Bounds": ",".join(f"{b:.4f}" for b in bounds),
                             "Access-Control-Expose-Headers": "X-Plan-Bounds",
                             "Cache-Control": "no-cache"})


@router.post("/coverage")
def indoor_coverage(req: IndoorCoverageRequest) -> dict:
    """COST-231 multi-wall coverage heatmap over the uploaded floor plan."""
    session = _session_or_404(req.dxf_id)
    walls = extract_walls(session.document(), req.layer_materials)

    # Link parameters: technology preset (if any) overridden per request.
    tech = get_technology(req.technology) if req.technology else {
        "freq_mhz": 2442.0, "tx_power_dbm": 20.0, "tx_gain_dbi": 3.0,
        "rx_gain_dbi": 0.0, "losses_db": 0.0, "rx_sensitivity_dbm": -82.0,
    }
    for f in ("freq_mhz", "tx_power_dbm", "tx_gain_dbi", "rx_gain_dbi",
              "losses_db", "rx_sensitivity_dbm"):
        v = getattr(req, f)
        if v is not None:
            tech[f] = v

    try:
        result = simulate_indoor(
            walls, req.tx_x, req.tx_y, float(tech["freq_mhz"]),
            unit_scale=req.unit_scale,
            tx_power_dbm=float(tech["tx_power_dbm"]),
            tx_gain_dbi=float(tech["tx_gain_dbi"]),
            rx_gain_dbi=float(tech["rx_gain_dbi"]),
            losses_db=float(tech["losses_db"]),
            rx_sensitivity_dbm=float(tech["rx_sensitivity_dbm"]),
            tx_height_m=req.tx_height_m, rx_height_m=req.rx_height_m,
            grid_px=req.grid_px)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    results_store.save("indoor", result.result_id, result.png,
                       {"bounds_dxf": result.bounds_dxf})

    return {
        "result_id": result.result_id,
        "png_url": f"/api/indoor/coverage/{result.result_id}.png",
        "bounds_dxf": result.bounds_dxf,
        "legend": result.legend,
        "stats": result.stats,
        "warnings": result.warnings,
    }


@router.get("/coverage/{result_id}.png")
def indoor_coverage_png(result_id: str) -> Response:
    hit = results_store.load("indoor", result_id)
    if hit is None:
        raise HTTPException(404, "Indoor coverage result expired or unknown")
    return Response(content=hit[0], media_type="image/png",
                    headers={"Cache-Control": "max-age=3600"})


# ------------------------------------------------------- tunnels & TTE
@router.get("/tunnel")
def tunnel_study(
    freq_mhz: float = Query(446.0, gt=0),
    width_m: float = Query(4.0, gt=0.5, le=30),
    height_m: float = Query(3.0, gt=0.5, le=30),
    length_m: float = Query(2000.0, gt=10, le=50_000),
    wall: str = Query("rock"),
    polarization: str = Query("horizontal"),
    roughness_m: float = Query(0.1, ge=0, le=1),
    tilt_deg: float = Query(0.0, ge=0, le=10),
    tx_power_dbm: float = Query(30.0),
    tx_gain_dbi: float = Query(6.0),
    rx_gain_dbi: float = Query(0.0),
    losses_db: float = Query(0.0),
    rx_sensitivity_dbm: float = Query(-100.0),
) -> dict:
    """Waveguide-regime signal profile along a tunnel / mine gallery."""
    if wall not in TUNNEL_WALL_PRESETS:
        raise HTTPException(422, f"Unknown tunnel wall preset: {wall!r}")
    return {
        "wall": wall, "freq_mhz": freq_mhz,
        **tunnel_profile(freq_mhz, width_m, height_m, length_m,
                         eps_r=TUNNEL_WALL_PRESETS[wall]["eps_r"],
                         polarization=polarization, roughness_m=roughness_m,
                         tilt_deg=tilt_deg, tx_power_dbm=tx_power_dbm,
                         tx_gain_dbi=tx_gain_dbi, rx_gain_dbi=rx_gain_dbi,
                         losses_db=losses_db,
                         rx_sensitivity_dbm=rx_sensitivity_dbm),
    }


@router.get("/tte")
def tte_study(
    freq_hz: float = Query(5000.0, gt=10, le=1e6),
    depth_m: float = Query(100.0, gt=1, le=2000),
    earth: str = Query("average_soil"),
    tx_power_dbm: float = Query(30.0),
    system_gain_db: float = Query(20.0),
    rx_sensitivity_dbm: float = Query(-130.0),
) -> dict:
    """Through-the-earth (mine/cave) link budget through conductive ground."""
    if earth not in EARTH_PRESETS:
        raise HTTPException(422, f"Unknown earth preset: {earth!r}")
    return {
        "earth": earth, "freq_hz": freq_hz, "depth_m": depth_m,
        **tte_link(freq_hz, depth_m, EARTH_PRESETS[earth]["sigma"],
                   tx_power_dbm=tx_power_dbm, system_gain_db=system_gain_db,
                   rx_sensitivity_dbm=rx_sensitivity_dbm),
    }


def _session_or_404(dxf_id: str):
    session = get_dxf_store().get(dxf_id)
    if session is None:
        raise HTTPException(404, f"Unknown DXF id: {dxf_id}")
    if not session.layers:
        from ..services.dxf import parser
        session.layers = parser.list_layers(session.document())
    return session
