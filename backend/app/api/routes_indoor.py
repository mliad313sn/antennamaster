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


# ===================================================================== #
#  Phase 2 — Radiating cable (leaky feeder) for metro / underground mine
# ===================================================================== #
from ..services.rf.underground import (LEAKY_CABLE_PRESETS,  # noqa: E402
                                       leaky_feeder_profile)


@router.get("/leaky-cables")
def leaky_cables() -> dict:
    """Radiating-cable presets (loss dB/100 m, coupling loss) for the leaky
    feeder tool."""
    return {"cables": [{"key": k, **v} for k, v in LEAKY_CABLE_PRESETS.items()]}


class LeakyFeederRequest(BaseModel):
    freq_mhz: float = Field(450.0, gt=0)
    cable: str = "rc78"
    cable_length_m: float | None = Field(None, gt=1, le=50_000)
    # Optional: measure the cable run straight from a DXF polyline layer.
    dxf_id: str | None = None
    cable_layer: str | None = None
    unit_scale: float = Field(1.0, gt=0)
    # Cable/electrical overrides:
    loss_db_100m: float | None = Field(None, gt=0, le=50)
    coupling_db: float | None = Field(None, gt=0, le=120)
    head_end_dbm: float = Field(20.0, ge=-10, le=50)
    amp_gain_db: float = Field(30.0, ge=0, le=90)
    amp_output_dbm: float | None = None
    rx_sensitivity_dbm: float = Field(-95.0, le=0)
    design_margin_db: float = Field(10.0, ge=0, le=40)
    radial_distance_m: float = Field(2.0, gt=0, le=50)
    coupling_reference_m: float = Field(2.0, gt=0, le=50)
    auto_amplifiers: bool = True


@router.post("/leaky-feeder")
def leaky_feeder_study(req: LeakyFeederRequest,
                       user: dict | None = Depends(current_user)) -> dict:
    """Radiating-cable link design along a tunnel/metro/mine run: RX vs
    distance, auto-placed inline amplifiers to hold a target margin, and the
    "moving-train" continuous-service KPI (percent of the run above threshold
    plus the worst coverage gap).  The cable length may be given directly or
    measured from a designated DXF polyline layer."""
    if req.cable not in LEAKY_CABLE_PRESETS:
        raise HTTPException(422, f"Unknown radiating cable: {req.cable!r}")

    length_m = req.cable_length_m
    measured_from_dxf = False
    if length_m is None:
        if not (req.dxf_id and req.cable_layer):
            raise HTTPException(422, "Provide cable_length_m, or dxf_id + "
                                     "cable_layer to measure the run from a drawing.")
        session = _session_or_404(req.dxf_id, user)
        from ..services.indoor.floorplan import layer_polyline_length
        length_m = layer_polyline_length(session.document(), req.cable_layer,
                                         req.unit_scale)
        measured_from_dxf = True
        if length_m <= 1.0:
            raise HTTPException(422, f"Layer {req.cable_layer!r} has no "
                                     "measurable linework to use as a cable run.")

    result = leaky_feeder_profile(
        req.freq_mhz, length_m, cable=req.cable,
        loss_db_100m=req.loss_db_100m, coupling_db=req.coupling_db,
        head_end_dbm=req.head_end_dbm, amp_gain_db=req.amp_gain_db,
        amp_output_dbm=req.amp_output_dbm,
        rx_sensitivity_dbm=req.rx_sensitivity_dbm,
        design_margin_db=req.design_margin_db,
        radial_distance_m=req.radial_distance_m,
        coupling_reference_m=req.coupling_reference_m,
        auto_amplifiers=req.auto_amplifiers)
    return {"freq_mhz": req.freq_mhz, "cable_length_m": round(length_m, 1),
            "cable_length_from_dxf": measured_from_dxf, **result}


# ===================================================================== #
#  Phase 3 — Automated AP / site placement solver
# ===================================================================== #
from ..services.rf import apsolver as _apsolver  # noqa: E402


class ApSolveRequest(BaseModel):
    dxf_id: str
    layer_materials: dict[str, str] = Field(default_factory=dict)
    unit_scale: float = Field(1.0, gt=0)          # meters per drawing unit
    # Radio:
    freq_mhz: float = Field(5800.0, gt=0)
    tx_power_dbm: float = Field(20.0)
    tx_gain_dbi: float = Field(3.0)
    rx_gain_dbi: float = Field(0.0)
    target_rssi_dbm: float = Field(-67.0, le=0)   # coverage design threshold
    roaming_threshold_dbm: float = Field(-67.0, le=0)
    target_coverage: float = Field(0.98, gt=0, le=1.0)
    ceiling_z_m: float = Field(2.7, gt=0, le=50)
    # Discretization (meters):
    demand_spacing_m: float = Field(4.0, gt=0.5, le=50)
    candidate_spacing_m: float = Field(8.0, gt=1.0, le=100)
    max_aps: int = Field(40, ge=1, le=200)
    # Capacity:
    user_density_per_100m2: float = Field(0.0, ge=0)
    users_per_ap: int = Field(40, ge=1, le=200)
    throughput_demand_mbps: float = Field(0.0, ge=0)
    ap_capacity_mbps: float = Field(600.0, gt=0)
    band: str = Field("5GHz", pattern="^(2\\.4GHz|5GHz|6GHz)$")


@router.post("/ap-solve")
def ap_solve(req: ApSolveRequest,
             user: dict | None = Depends(current_user)) -> dict:
    """Solve an indoor AP layout over a DXF floor plan: the minimum number of
    access points and their [x, y, z] positions to hit the coverage target,
    grown to meet user-density / throughput capacity, with a -67 dBm roaming
    overlap check and non-overlapping channel assignment (graph colouring)."""
    require_feature(user, "indoor_studio")
    session = _session_or_404(req.dxf_id, user)
    walls = extract_walls(session.document(), req.layer_materials)

    x0, y0, x1, y1 = walls.bbox() if walls.count else (0.0, 0.0,
                                                       100.0 / req.unit_scale,
                                                       100.0 / req.unit_scale)
    bbox = (x0, y0, x1, y1)
    area_m2 = abs((x1 - x0) * (y1 - y0)) * req.unit_scale ** 2

    demand = _apsolver.make_grid(bbox, req.demand_spacing_m / req.unit_scale)
    candidates = _apsolver.make_grid(
        bbox, req.candidate_spacing_m / req.unit_scale,
        inset=req.candidate_spacing_m / req.unit_scale * 0.25)
    if demand.shape[0] * candidates.shape[0] > 4_000_000:
        raise HTTPException(422, "Grid too fine for this area; increase "
                                 "demand_spacing_m / candidate_spacing_m.")

    rssi = _apsolver.build_indoor_rssi(
        walls if walls.count else None, candidates, demand, req.freq_mhz,
        req.unit_scale, req.tx_power_dbm, req.tx_gain_dbi, req.rx_gain_dbi)

    sol = _apsolver.solve_layout(
        rssi, candidates, demand, target_rssi_dbm=req.target_rssi_dbm,
        target_coverage=req.target_coverage,
        roaming_threshold_dbm=req.roaming_threshold_dbm, max_aps=req.max_aps,
        area_m2=area_m2, user_density_per_100m2=req.user_density_per_100m2,
        users_per_ap=req.users_per_ap,
        throughput_demand_mbps=req.throughput_demand_mbps,
        ap_capacity_mbps=req.ap_capacity_mbps, ceiling_z_m=req.ceiling_z_m,
        channels=_apsolver.CHANNEL_PLANS[req.band], unit_scale=req.unit_scale)

    return {
        "dxf_id": req.dxf_id, "band": req.band,
        "area_m2": round(area_m2, 1),
        "bbox_dxf": [round(v, 3) for v in bbox],
        "ap_count": sol.ap_count,
        "aps": sol.aps,
        "coverage_fraction": sol.coverage_fraction,
        "roaming_fraction": sol.roaming_fraction,
        "capacity": sol.capacity,
        "channel_plan": {"cochannel_conflicts": sol.channel_plan["cochannel_conflicts"],
                         "colors_used": sol.channel_plan["colors_used"]},
        "demand_points": sol.demand_points,
        "warnings": sol.warnings,
    }
