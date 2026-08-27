"""Indoor & underground study endpoints.

Reuses the DXF upload store: the same uploaded file can be treated as
terrain relief (georeferencing pipeline) or as a structural floor plan /
mine gallery layout (this module) — the user decides per study.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..services import results_store
from ..services.dxf.store import get_dxf_store
from ..services.indoor.engine import simulate_indoor
from ..services.saas.tiers import require_feature
from .routes_auth import current_user
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
    # Multi-floor: number of slabs between TX and the mapped RX floor,
    # storey height, and the COST-231 per-floor penetration (18.3 dB is the
    # standard concrete-slab value; the total saturates non-linearly).
    floors_crossed: int = Field(0, ge=0, le=30)
    floor_height_m: float = Field(3.0, ge=2, le=6)
    floor_loss_db: float = Field(18.3, ge=0, le=40)
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
def floorplan_preview(dxf_id: str, layers: str = Query(""),
                      user: dict | None = Depends(current_user)) -> Response:
    """Wall linework preview so the user can click a TX position.

    ``layers`` is a comma-separated list; empty = all layers.  The DXF-unit
    bounds of the image are returned in the X-Plan-Bounds header
    (``x0,y0,x1,y1``) for click-coordinate mapping.
    """
    session = _session_or_404(dxf_id, user)
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
def indoor_coverage(req: IndoorCoverageRequest,
                    user: dict | None = Depends(current_user)) -> dict:
    """COST-231 multi-wall coverage heatmap over the uploaded floor plan."""
    require_feature(user, "indoor_studio")   # Pro-tier capability in SaaS mode
    session = _session_or_404(req.dxf_id, user)
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
            floors_crossed=req.floors_crossed,
            floor_height_m=req.floor_height_m,
            floor_loss_db=req.floor_loss_db,
            grid_px=req.grid_px)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    results_store.save("indoor", result.result_id, result.png,
                       {"bounds_dxf": result.bounds_dxf,
                        "owner_id": user["id"] if user else None})

    return {
        "result_id": result.result_id,
        "png_url": f"/api/indoor/coverage/{result.result_id}.png",
        "bounds_dxf": result.bounds_dxf,
        "legend": result.legend,
        "stats": result.stats,
        "warnings": result.warnings,
    }


class AutoPlaceRequest(BaseModel):
    dxf_id: str
    layer_materials: dict[str, str]
    unit_scale: float = Field(1.0, gt=0)
    technology: str | None = None
    freq_mhz: float | None = Field(None, gt=0)
    tx_power_dbm: float | None = None
    tx_gain_dbi: float | None = None
    rx_gain_dbi: float | None = None
    losses_db: float | None = None
    rx_sensitivity_dbm: float | None = None
    target_margin_db: float = Field(0.0, ge=0, le=40)
    tx_height_m: float = Field(2.7, gt=0)
    rx_height_m: float = Field(1.2, gt=0)
    coverage_target: float = Field(0.95, ge=0.5, le=1.0)
    max_aps: int = Field(24, ge=1, le=60)
    candidate_grid: int = Field(8, ge=3, le=16)
    demand_grid: int = Field(24, ge=8, le=48)
    band: str = Field("2.4GHz")
    roaming_threshold_dbm: float = Field(-67.0, le=0)
    # Capacity-aware sizing (optional):
    users_total: int = Field(0, ge=0, le=100_000)
    throughput_per_user_mbps: float = Field(0.0, ge=0, le=1000)
    ap_capacity_mbps: float = Field(600.0, gt=0, le=10_000)


@router.post("/auto-place")
def auto_place(req: AutoPlaceRequest,
               user: dict | None = Depends(current_user)) -> dict:
    """Solve AP count, positions and channel plan for a coverage (+capacity)
    target over the floor plan - the inverse of the heatmap.  Reuses the same
    multi-wall path-loss model, so the design matches the coverage view."""
    require_feature(user, "indoor_studio")
    session = _session_or_404(req.dxf_id, user)
    walls = extract_walls(session.document(), req.layer_materials)
    if walls.count == 0:
        raise HTTPException(422, "No wall segments on the selected layers")

    tech = get_technology(req.technology) if req.technology else {
        "freq_mhz": 2442.0, "tx_power_dbm": 20.0, "tx_gain_dbi": 3.0,
        "rx_gain_dbi": 0.0, "losses_db": 0.0, "rx_sensitivity_dbm": -72.0}
    for f in ("freq_mhz", "tx_power_dbm", "tx_gain_dbi", "rx_gain_dbi",
              "losses_db", "rx_sensitivity_dbm"):
        v = getattr(req, f)
        if v is not None:
            tech[f] = v

    from ..services.indoor.placement import auto_place_aps
    try:
        return auto_place_aps(
            walls, float(tech["freq_mhz"]),
            tx_power_dbm=float(tech["tx_power_dbm"]),
            tx_gain_dbi=float(tech["tx_gain_dbi"]),
            rx_gain_dbi=float(tech["rx_gain_dbi"]),
            losses_db=float(tech["losses_db"]),
            rx_sensitivity_dbm=float(tech["rx_sensitivity_dbm"]),
            target_margin_db=req.target_margin_db, unit_scale=req.unit_scale,
            tx_height_m=req.tx_height_m, rx_height_m=req.rx_height_m,
            coverage_target=req.coverage_target, max_aps=req.max_aps,
            candidate_grid=req.candidate_grid, demand_grid=req.demand_grid,
            band=req.band, roaming_threshold_dbm=req.roaming_threshold_dbm,
            users_total=req.users_total,
            throughput_per_user_mbps=req.throughput_per_user_mbps,
            ap_capacity_mbps=req.ap_capacity_mbps)
    except Exception as exc:
        raise HTTPException(502, f"Auto-placement failed: {exc}") from exc


class DasRequest(BaseModel):
    dxf_id: str
    layer_materials: dict[str, str]
    unit_scale: float = Field(1.0, gt=0)
    freq_mhz: float = Field(2442.0, gt=0)
    source_power_dbm: float = Field(30.0, ge=-30, le=60)
    tree: dict                                   # DAS component tree
    rx_gain_dbi: float = Field(0.0, ge=-10, le=20)
    rx_sensitivity_dbm: float = Field(-82.0, le=0)
    tx_height_m: float = Field(2.7, gt=0)
    rx_height_m: float = Field(1.2, gt=0)
    grid_px: int = Field(200, ge=50, le=400)


@router.post("/das")
def das_design(req: DasRequest,
               user: dict | None = Depends(current_user)) -> dict:
    """Solve a DAS component tree (cables, splitters, tap couplers → antennas)
    and render the combined multi-antenna coverage: per-antenna delivered
    power/EIRP + strongest-server heatmap over the floor plan."""
    require_feature(user, "indoor_studio")
    session = _session_or_404(req.dxf_id, user)
    walls = extract_walls(session.document(), req.layer_materials)
    if walls.count == 0:
        raise HTTPException(422, "No wall segments on the selected layers")

    from ..services.indoor.das import DasError, das_coverage, solve_das
    try:
        antennas = solve_das(req.source_power_dbm, req.tree)
    except DasError as exc:
        raise HTTPException(422, f"Invalid DAS tree: {exc}") from exc

    result = das_coverage(walls, antennas, req.freq_mhz,
                          unit_scale=req.unit_scale,
                          rx_gain_dbi=req.rx_gain_dbi,
                          rx_sensitivity_dbm=req.rx_sensitivity_dbm,
                          tx_height_m=req.tx_height_m,
                          rx_height_m=req.rx_height_m, grid_px=req.grid_px)
    results_store.save("indoor", result.result_id, result.png,
                       {"bounds_dxf": result.bounds_dxf,
                        "owner_id": user["id"] if user else None})
    return {"result_id": result.result_id,
            "png_url": f"/api/indoor/coverage/{result.result_id}.png",
            "bounds_dxf": result.bounds_dxf, "legend": result.legend,
            "stats": result.stats, "antennas": antennas}


class FloorIn(BaseModel):
    level: int = Field(ge=-10, le=200)
    dxf_id: str
    layer_materials: dict[str, str]


class FloorStackRequest(BaseModel):
    floors: list[FloorIn] = Field(min_length=1, max_length=30)
    tx_level: int = Field(0, ge=-10, le=200)
    tx_x: float
    tx_y: float
    unit_scale: float = Field(1.0, gt=0)
    freq_mhz: float = Field(2442.0, gt=0)
    tx_power_dbm: float = Field(20.0, ge=-30, le=60)
    tx_gain_dbi: float = Field(3.0, ge=-10, le=30)
    rx_gain_dbi: float = Field(0.0, ge=-10, le=20)
    losses_db: float = Field(0.0, ge=0, le=30)
    rx_sensitivity_dbm: float = Field(-82.0, le=0)
    floor_height_m: float = Field(3.0, ge=2, le=6)
    floor_loss_db: float = Field(18.3, ge=0, le=40)
    grid_px: int = Field(150, ge=50, le=400)


@router.post("/stack")
def floor_stack(req: FloorStackRequest,
                user: dict | None = Depends(current_user)) -> dict:
    """Multi-floor building study: one plan per storey, a single TX on
    ``tx_level``; each floor's heatmap uses ITS OWN walls plus the COST-231
    slab penetration for the storeys crossed — the whole building at once."""
    require_feature(user, "indoor_studio")
    floors_out = []
    for fl in sorted(req.floors, key=lambda f: f.level):
        session = _session_or_404(fl.dxf_id, user)
        walls = extract_walls(session.document(), fl.layer_materials)
        crossed = abs(fl.level - req.tx_level)
        try:
            result = simulate_indoor(
                walls, req.tx_x, req.tx_y, req.freq_mhz,
                unit_scale=req.unit_scale, tx_power_dbm=req.tx_power_dbm,
                tx_gain_dbi=req.tx_gain_dbi, rx_gain_dbi=req.rx_gain_dbi,
                losses_db=req.losses_db,
                rx_sensitivity_dbm=req.rx_sensitivity_dbm,
                floors_crossed=crossed, floor_height_m=req.floor_height_m,
                floor_loss_db=req.floor_loss_db, grid_px=req.grid_px)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        results_store.save("indoor", result.result_id, result.png,
                           {"bounds_dxf": result.bounds_dxf,
                            "owner_id": user["id"] if user else None})
        floors_out.append({
            "level": fl.level, "floors_crossed": crossed,
            "result_id": result.result_id,
            "png_url": f"/api/indoor/coverage/{result.result_id}.png",
            "bounds_dxf": result.bounds_dxf,
            "stats": result.stats, "warnings": result.warnings})
    served = [f["stats"]["served_area_fraction"] for f in floors_out]
    return {"tx_level": req.tx_level, "floors": floors_out,
            "building_mean_served_fraction": round(sum(served) / len(served), 4)}


@router.get("/coverage/{result_id}.png")
def indoor_coverage_png(result_id: str,
                        user: dict | None = Depends(current_user)) -> Response:
    """An indoor heatmap, owner-scoped.

    Outdoor coverage was hardened against this and indoor was left behind,
    which made a result id a capability here: anyone holding the 12-hex id
    could read the heatmap. What that leaks is not a colour ramp — it is a
    building's interior, drawn to scale from the customer's own floor plan,
    with the wall materials and the DAS layout that were studied. For a
    hospital, a prison, a mine gallery or a public-safety site that is the
    same class of confidential information the outdoor fix exists to protect,
    and arguably a more sensitive one.

    Mirrors ``resolve_result``: results with no owner (the anonymous
    self-hosted default) stay open, and someone else's result answers 404
    rather than 403 so the id is not an existence oracle.
    """
    hit = results_store.load("indoor", result_id)
    if hit is None:
        raise HTTPException(404, "Indoor coverage result expired or unknown")
    owner = (hit[1] or {}).get("owner_id")
    if owner is not None and (user is None or user.get("id") != owner):
        raise HTTPException(404, "Indoor coverage result expired or unknown")
    # Private to one account: a shared cache must never hand it to the next
    # requester, who by definition is a different tenant.
    cache = "max-age=3600" if owner is None else "private, max-age=3600"
    return Response(content=hit[0], media_type="image/png",
                    headers={"Cache-Control": cache})


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


class BendIn(BaseModel):
    position_m: float = Field(ge=0)
    radius_m: float = Field(30.0, gt=1, le=1000)
    angle_deg: float = Field(90.0, ge=0, le=180)
    width_m: float = Field(5.0, gt=0.5, le=30)


class LeakyFeederRequest(BaseModel):
    freq_mhz: float = Field(450.0, gt=0)
    length_m: float = Field(1000.0, gt=10, le=20_000)
    cable_atten_db_per_100m: float = Field(3.0, gt=0, le=50)
    coupling_ref_db: float = Field(65.0, ge=20, le=110)
    coupling_ref_m: float = Field(2.0, gt=0.1, le=20)
    lateral_m: float = Field(2.0, gt=0.1, le=30)
    tx_power_dbm: float = Field(20.0, ge=-30, le=60)
    rx_sensitivity_dbm: float = Field(-95.0, le=0)
    system_margin_db: float = Field(10.0, ge=0, le=40)
    amp_gain_db: float = Field(0.0, ge=0, le=40)
    amp_spacing_m: float | None = Field(None, gt=10, le=5000)
    bends: list[BendIn] = Field(default_factory=list, max_length=50)


@router.post("/leaky-feeder")
def leaky_feeder_study(req: LeakyFeederRequest) -> dict:
    """Radiating-cable (leaky feeder) field profile along a tunnel run, with
    inline-amplifier spacing and bend losses - the real metro/mine solution,
    not a bare waveguide.  Reports served length, worst gap and amps required."""
    from ..services.rf.leakyfeeder import leaky_feeder_profile
    return {"freq_mhz": req.freq_mhz, "length_m": req.length_m,
            **leaky_feeder_profile(
                req.freq_mhz, req.length_m, req.cable_atten_db_per_100m,
                coupling_ref_db=req.coupling_ref_db,
                coupling_ref_m=req.coupling_ref_m, lateral_m=req.lateral_m,
                tx_power_dbm=req.tx_power_dbm,
                rx_sensitivity_dbm=req.rx_sensitivity_dbm,
                system_margin_db=req.system_margin_db,
                amp_gain_db=req.amp_gain_db, amp_spacing_m=req.amp_spacing_m,
                bends=[b.model_dump() for b in req.bends])}


@router.get("/tunnel-das")
def tunnel_das_study(
    freq_mhz: float = Query(450.0, gt=0),
    width_m: float = Query(5.0, gt=0.5, le=30),
    height_m: float = Query(4.0, gt=0.5, le=30),
    length_m: float = Query(2000.0, gt=10, le=50_000),
    wall: str = Query("concrete"),
    tx_power_dbm: float = Query(20.0),
    tx_gain_dbi: float = Query(6.0),
    rx_gain_dbi: float = Query(0.0),
    losses_db: float = Query(0.0),
    rx_sensitivity_dbm: float = Query(-95.0),
    overlap_pct: float = Query(15.0, ge=0, le=90),
) -> dict:
    """Distributed-antenna (DAS) tunnel design: single-antenna reach from the
    Emslie waveguide, then how many antennas and at what spacing give
    continuous coverage over the run."""
    if wall not in TUNNEL_WALL_PRESETS:
        raise HTTPException(422, f"Unknown tunnel wall preset: {wall!r}")
    from ..services.rf.leakyfeeder import distributed_antenna_tunnel
    return {"wall": wall, "freq_mhz": freq_mhz, "length_m": length_m,
            **distributed_antenna_tunnel(
                freq_mhz, width_m, height_m, length_m,
                eps_r=TUNNEL_WALL_PRESETS[wall]["eps_r"],
                tx_power_dbm=tx_power_dbm, tx_gain_dbi=tx_gain_dbi,
                rx_gain_dbi=rx_gain_dbi, losses_db=losses_db,
                rx_sensitivity_dbm=rx_sensitivity_dbm, overlap_pct=overlap_pct)}


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


def _session_or_404(dxf_id: str, user: dict | None = None):
    session = get_dxf_store().get(dxf_id)
    if session is None:
        raise HTTPException(404, f"Unknown DXF id: {dxf_id}")
    # Cross-tenant guard: a floor plan uploaded by an account is private to
    # it (its wall geometry is confidential); ownerless plans stay open.
    from .routes_dxf import _check_owner
    _check_owner(session, user)
    if not session.layers:
        from ..services.dxf import parser
        session.layers = parser.list_layers(session.document())
    return session
