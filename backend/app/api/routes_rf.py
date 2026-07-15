"""RF study endpoints: technology presets, propagation models, area coverage."""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..services import results_store
from ..services.rf import antenna as antenna_store
from ..services.rf.models import MODEL_INFO
from ..services.rf.technologies import TECHNOLOGIES, get_technology
from ..services.saas import jobs
from ..services.saas.tiers import check_preset_allowed, require_feature
from ..services.terrain.coverage import CoverageEngine, composite_best_server
from .routes_auth import current_user
from .routes_terrain import resolve_fusion

router = APIRouter(prefix="/api/rf", tags=["rf"])


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
    # Measured pattern (MSI Planet upload) replacing the parametric model:
    antenna_id: str | None = None
    downtilt_deg: float = Field(0.0, ge=-10, le=20)
    vertical_beamwidth_deg: float = Field(10.0, gt=1, le=90)
    # Location-variability (shadow fade) margin subtracted before the
    # served test - design to ~90/95% area instead of the 50% median.
    shadow_margin_db: float = Field(0.0, ge=0, le=30)
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    # Environmental excess losses (last-mile clutter / weather):
    foliage_depth_m: float = Field(0.0, ge=0, le=400)
    rain_rate_mm_h: float = Field(0.0, ge=0, le=150)
    # ITU-R P.2108 statistical man-made clutter: percentage of locations
    # not exceeded (0 = off, 50 = median urban clutter, 90 = conservative).
    clutter_pct: float = Field(0.0, ge=0, le=99.9)
    # Simulate on the surface model (DSM) instead of bare terrain;
    # requires AM_DSM_URL to be configured on the server.
    surface: bool = False
    # Simulation resolution:
    n_radials: int = Field(180, ge=36, le=720)
    n_steps: int = Field(100, ge=20, le=400)
    raster_px: int = Field(512, ge=128, le=1024)


@router.get("/technologies")
def list_technologies() -> dict:
    """All radio-study presets (2G/3G/4G/5G, PMR, broadcast, WLAN, IoT, PtP)."""
    return {"technologies": [{"key": k, **v} for k, v in TECHNOLOGIES.items()]}


@router.get("/models")
def list_models() -> dict:
    """All propagation models with validity ranges."""
    return {"models": [{"key": k, **v} for k, v in MODEL_INFO.items()]}


@router.get("/equipment")
def list_equipment() -> dict:
    """Hardware Catalog — real equipment profiles (Wi-Fi, Private LTE, PTP
    microwave, PMR) for the Equipment Selector.  Selecting one auto-fills the
    RF parameters; users can still override any field."""
    from ..services.rf.hardware import categories, list_equipment as _list
    return {"equipment": _list(), "categories": categories()}


@router.get("/scenarios")
def list_scenarios() -> dict:
    """Plain-language deployment scenarios for Simple Mode - each maps an
    outcome ('connect two buildings') to a technology preset + study
    defaults.  ``label``/``blurb`` are i18n keys resolved in the frontend."""
    from ..services.rf.scenarios import list_scenarios as _list
    return {"scenarios": _list()}


@router.get("/scenarios/{scenario_id}")
def resolve_scenario(scenario_id: str) -> dict:
    """Full study parameters for one scenario (the preset + heights + radius
    + antenna the physics engine needs)."""
    from ..services.rf.scenarios import resolve_scenario as _resolve
    try:
        return _resolve(scenario_id)
    except KeyError:
        raise HTTPException(404, f"Unknown scenario: {scenario_id}")


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
def simulate_coverage(req: CoverageRequest,
                      user: dict | None = Depends(current_user)) -> dict:
    """Run an area coverage simulation from a TX site over the fused terrain."""
    check_preset_allowed(user, req.technology)
    try:
        with jobs.sim_slot():
            return run_coverage(req, user=user)
    except jobs.SimBusyError as exc:
        raise HTTPException(429, str(exc)) from exc


def _load_pattern(antenna_id: str, user: dict | None) -> dict:
    """Owner-scoped antenna load: 404 unknown, 403 another tenant's private
    pattern (never leak that it exists to a non-owner)."""
    try:
        pattern = antenna_store.load_antenna(
            antenna_id, owner_id=user["id"] if user else None)
    except antenna_store.AntennaAccessError:
        raise HTTPException(403, "This antenna pattern belongs to another account")
    if pattern is None:
        raise HTTPException(404, f"Unknown antenna id: {antenna_id}")
    return pattern


def run_coverage(req: CoverageRequest, progress_cb=None,
                 user: dict | None = None) -> dict:
    """Shared implementation for the sync endpoint and background jobs."""
    tech = _resolve_tech(req)

    grid = georef = None
    if req.dxf_id:
        from .routes_dxf import resolve_dxf
        session = resolve_dxf(req.dxf_id, user)   # owner + dxf_fusion gate
        grid, georef = session.grid, session.georef

    pattern = None
    if req.antenna_id:
        pattern = _load_pattern(req.antenna_id, user)
        # A measured pattern carries its own gain; use it unless overridden.
        if req.tx_gain_dbi is None:
            tech["tx_gain_dbi"] = float(pattern.get("gain_dbi", tech["tx_gain_dbi"]))

    engine = CoverageEngine(resolve_fusion(req.surface))
    try:
        result = engine.simulate(
            req.lat, req.lon, tech, radius_m=req.radius_km * 1000.0,
            n_radials=req.n_radials, n_steps=req.n_steps,
            antenna_azimuth_deg=req.antenna_azimuth_deg,
            antenna_beamwidth_deg=req.antenna_beamwidth_deg,
            downtilt_deg=req.downtilt_deg,
            vertical_beamwidth_deg=req.vertical_beamwidth_deg,
            antenna_pattern=pattern,
            shadow_margin_db=req.shadow_margin_db,
            foliage_depth_m=req.foliage_depth_m,
            rain_rate_mm_h=req.rain_rate_mm_h,
            clutter_pct=req.clutter_pct,
            k=req.k_factor,
            grid=grid, georef=georef,
            raster_px=req.raster_px,
            progress_cb=progress_cb,
        )
    except Exception as exc:  # DEM fetch failure -> 502, not a stacktrace
        raise HTTPException(502, f"Coverage simulation failed: {exc}") from exc

    # Disk-backed so any worker can serve the PNG and restarts lose nothing.
    results_store.save("coverage", result.coverage_id, result.png,
                       {"bounds": result.bounds})

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
    hit = results_store.load("coverage", coverage_id)
    if hit is None:
        raise HTTPException(404, "Coverage result expired or unknown")
    return Response(content=hit[0], media_type="image/png",
                    headers={"Cache-Control": "max-age=3600"})


@router.get("/coverage/{coverage_id}.tif")
def coverage_geotiff(coverage_id: str) -> Response:
    """Coverage raster as a georeferenced GeoTIFF (EPSG:4326) - the GIS-native
    format ArcGIS/QGIS/Atoll/Pathloss import directly, unlike a bare PNG."""
    hit = results_store.load("coverage", coverage_id)
    if hit is None:
        raise HTTPException(404, "Coverage result expired or unknown")
    png, meta = hit
    from ..services.geotiff import rgba_png_to_geotiff
    bounds = meta.get("bounds", [[0, 0], [0, 0]])
    tif = rgba_png_to_geotiff(png, bounds)
    return Response(
        content=tif, media_type="image/tiff",
        headers={"Content-Disposition":
                 f'attachment; filename="coverage-{coverage_id}.tif"'})


@router.get("/coverage/{coverage_id}.kmz")
def coverage_kmz(coverage_id: str) -> Response:
    """Coverage raster as a KMZ GroundOverlay - opens in Google Earth / GIS,
    the deliverable format planners hand to clients."""
    hit = results_store.load("coverage", coverage_id)
    if hit is None:
        raise HTTPException(404, "Coverage result expired or unknown")
    png, meta = hit
    (south, west), (north, east) = meta.get("bounds", [[0, 0], [0, 0]])
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <GroundOverlay>
    <name>AntennaMaster coverage {coverage_id}</name>
    <Icon><href>coverage.png</href></Icon>
    <LatLonBox>
      <north>{north}</north><south>{south}</south>
      <east>{east}</east><west>{west}</west>
    </LatLonBox>
  </GroundOverlay>
</kml>"""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml)
        z.writestr("coverage.png", png)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.google-earth.kmz",
        headers={"Content-Disposition":
                 f'attachment; filename="coverage-{coverage_id}.kmz"'})


# ----------------------------------------------------------- antennas (MSI)
@router.post("/antenna")
async def upload_antenna(file: UploadFile = File(...),
                         user: dict | None = Depends(current_user)) -> dict:
    """Upload an MSI Planet (.msi/.pln/.ant) measured antenna pattern.
    Authenticated uploads are private to the uploading account."""
    raw = await file.read()
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(413, "Pattern file exceeds 2 MB")
    try:
        text = raw.decode("utf-8", errors="replace")
        return antenna_store.save_antenna(text,
                                          owner_id=user["id"] if user else None)
    except ValueError as exc:
        raise HTTPException(422, f"Could not parse antenna pattern: {exc}") from exc


@router.get("/antennas")
def list_antennas(user: dict | None = Depends(current_user)) -> dict:
    """Antenna patterns visible to the caller (own + public), with gains
    and -3 dB beamwidths."""
    return {"antennas": antenna_store.list_antennas(
        owner_id=user["id"] if user else None)}


# ------------------------------------------------ batch receiver analysis
class ReceiverIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    name: str | None = Field(None, max_length=80)
    rx_height_m: float | None = Field(None, gt=0, le=500)


class BatchRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)          # TX
    lon: float = Field(ge=-180, le=180)
    receivers: list[ReceiverIn] = Field(min_length=1, max_length=200)
    technology: str = "custom"
    dxf_id: str | None = None
    surface: bool = False
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    foliage_depth_m: float = Field(0.0, ge=0, le=400)
    rain_rate_mm_h: float = Field(0.0, ge=0, le=150)
    clutter_pct: float = Field(0.0, ge=0, le=99.9)
    # Link budget overrides (same semantics as /coverage):
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


@router.post("/batch")
def batch_receivers(req: BatchRequest, format: str = "json",
                    user: dict | None = Depends(current_user)) -> Response:
    """Qualify up to 200 receiver locations against one TX in a single call
    - the WISP/fixed-wireless workflow (per-receiver fused profile, Deygout
    diffraction, environmental losses, margin verdict).  ``?format=csv``
    returns the table as CSV for spreadsheets/CRMs."""
    require_feature(user, "batch_analysis")
    check_preset_allowed(user, req.technology)
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

    grid = georef = None
    if req.dxf_id:
        from .routes_dxf import resolve_dxf
        session = resolve_dxf(req.dxf_id, user)
        grid, georef = session.grid, session.georef

    from ..services.rf.planning import evaluate_receiver
    fusion = resolve_fusion(req.surface)
    rows = []
    try:
        with jobs.sim_slot():
            for i, r in enumerate(req.receivers):
                t = dict(tech)
                if r.rx_height_m is not None:
                    t["h_ut_m"] = r.rx_height_m
                res = evaluate_receiver(
                    fusion, t, req.lat, req.lon, r.lat, r.lon,
                    k=req.k_factor, foliage_depth_m=req.foliage_depth_m,
                    rain_rate_mm_h=req.rain_rate_mm_h,
                    clutter_pct=req.clutter_pct, grid=grid, georef=georef)
                rows.append({"name": r.name or f"RX {i + 1}",
                             "lat": r.lat, "lon": r.lon, **res})
    except jobs.SimBusyError as exc:
        raise HTTPException(429, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Batch analysis failed: {exc}") from exc

    served = sum(1 for r in rows if r["served"])
    if format == "csv":
        header = ["name", "lat", "lon", "distance_m", "rx_power_dbm",
                  "margin_db", "served", "los_clear",
                  "fresnel_clearance_ratio", "path_loss_db",
                  "diffraction_loss_db", "environment_loss_db"]
        lines = [",".join(header)]
        for r in rows:
            lines.append(",".join(str(r[h]) for h in header))
        return Response(
            content="\n".join(lines) + "\n", media_type="text/csv",
            headers={"Content-Disposition":
                     'attachment; filename="batch-receivers.csv"'})
    from fastapi.responses import JSONResponse
    return JSONResponse({
        "tx": {"lat": req.lat, "lon": req.lon},
        "technology": {**tech, "key": req.technology},
        "receivers": rows,
        "summary": {"total": len(rows), "served": served,
                    "served_fraction": round(served / len(rows), 4)},
    })


# ------------------------------------------------------- best-site search
class SiteSearchRequest(BaseModel):
    south: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    grid_n: int = Field(5, ge=2, le=7)
    technology: str = "custom"
    radius_km: float = Field(8.0, gt=0.1, le=50.0)
    shadow_margin_db: float = Field(0.0, ge=0, le=30)
    clutter_pct: float = Field(0.0, ge=0, le=99.9)
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    dxf_id: str | None = None
    surface: bool = False
    # Link budget overrides:
    freq_mhz: float | None = Field(None, gt=0)
    model: str | None = None
    environment: str | None = None
    tx_power_dbm: float | None = None
    rx_sensitivity_dbm: float | None = None
    h_bs_m: float | None = Field(None, gt=0)
    h_ut_m: float | None = Field(None, gt=0)


@router.post("/site-search")
def best_site_search(req: SiteSearchRequest,
                     user: dict | None = Depends(current_user)) -> dict:
    """Rank an n x n grid of candidate TX positions over a bounding box by
    coarse served-area fraction - "where should the mast go?".  Re-run the
    winner through /coverage at full resolution."""
    require_feature(user, "site_search")
    check_preset_allowed(user, req.technology)
    if not (req.north > req.south and req.east > req.west):
        raise HTTPException(422, "north/east must exceed south/west")
    try:
        tech = get_technology(req.technology)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for f in ("freq_mhz", "model", "environment", "tx_power_dbm",
              "rx_sensitivity_dbm", "h_bs_m", "h_ut_m"):
        v = getattr(req, f)
        if v is not None:
            tech[f] = v
    if tech["model"] not in MODEL_INFO:
        raise HTTPException(422, f"Unknown propagation model: {tech['model']!r}")

    grid = georef = None
    if req.dxf_id:
        from .routes_dxf import resolve_dxf
        session = resolve_dxf(req.dxf_id, user)
        grid, georef = session.grid, session.georef

    from ..services.rf.planning import site_search
    engine = CoverageEngine(resolve_fusion(req.surface))
    try:
        with jobs.sim_slot():
            candidates = site_search(
                engine, tech, req.south, req.west, req.north, req.east,
                grid_n=req.grid_n, radius_m=req.radius_km * 1000.0,
                shadow_margin_db=req.shadow_margin_db,
                clutter_pct=req.clutter_pct, k=req.k_factor,
                grid=grid, georef=georef)
    except jobs.SimBusyError as exc:
        raise HTTPException(429, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Site search failed: {exc}") from exc
    return {"candidates": candidates,
            "technology": {**tech, "key": req.technology},
            "note": "coarse 36x24 sweeps - re-run the winner via /coverage"}


# --------------------------------------------------------- multi-site study
class SiteIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    name: str | None = None
    antenna_azimuth_deg: float | None = Field(None, ge=0, lt=360)
    downtilt_deg: float = Field(0.0, ge=-10, le=20)


class MultiCoverageRequest(BaseModel):
    sites: list[SiteIn] = Field(min_length=1, max_length=8)
    technology: str = "custom"
    radius_km: float = Field(10.0, gt=0.1, le=150.0)
    dxf_id: str | None = None
    antenna_id: str | None = None
    antenna_beamwidth_deg: float = Field(65.0, gt=5, le=360)
    shadow_margin_db: float = Field(0.0, ge=0, le=30)
    foliage_depth_m: float = Field(0.0, ge=0, le=400)
    rain_rate_mm_h: float = Field(0.0, ge=0, le=150)
    clutter_pct: float = Field(0.0, ge=0, le=99.9)
    surface: bool = False
    vertical_beamwidth_deg: float = Field(10.0, gt=1, le=90)
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    # Co-channel SINR analysis (interference): thermal noise floor comes
    # from these; defaults or preset values are used when omitted.
    interference: bool = True
    bandwidth_mhz: float | None = Field(None, gt=0, le=400)
    noise_figure_db: float | None = Field(None, ge=0, le=20)
    n_radials: int = Field(120, ge=36, le=360)
    n_steps: int = Field(80, ge=20, le=200)
    raster_px: int = Field(768, ge=128, le=1024)
    # Link budget overrides shared by every site:
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


@router.post("/coverage/multi")
def simulate_multi_coverage(req: MultiCoverageRequest,
                            user: dict | None = Depends(current_user)) -> dict:
    """Best-server composite over up to 8 sites: each raster pixel takes the
    color of the site delivering the strongest served signal there - the
    cluster view planners use to check hand-over zones and holes."""
    require_feature(user, "multi_site")
    check_preset_allowed(user, req.technology)
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

    pattern = None
    if req.antenna_id:
        pattern = _load_pattern(req.antenna_id, user)
        if req.tx_gain_dbi is None:
            tech["tx_gain_dbi"] = float(pattern.get("gain_dbi", tech["tx_gain_dbi"]))

    grid = georef = None
    if req.dxf_id:
        from .routes_dxf import resolve_dxf
        session = resolve_dxf(req.dxf_id, user)
        grid, georef = session.grid, session.georef

    engine = CoverageEngine(resolve_fusion(req.surface))
    radius_m = req.radius_km * 1000.0
    computed = []
    warnings: list[str] = []
    try:
        with jobs.sim_slot():
            for s in req.sites:
                polar = engine.compute_polar(
                    s.lat, s.lon, dict(tech), radius_m=radius_m,
                    n_radials=req.n_radials, n_steps=req.n_steps,
                    antenna_azimuth_deg=s.antenna_azimuth_deg,
                    antenna_beamwidth_deg=req.antenna_beamwidth_deg,
                    downtilt_deg=s.downtilt_deg,
                    vertical_beamwidth_deg=req.vertical_beamwidth_deg,
                    antenna_pattern=pattern,
                    shadow_margin_db=req.shadow_margin_db,
                    foliage_depth_m=req.foliage_depth_m,
                    rain_rate_mm_h=req.rain_rate_mm_h,
                    clutter_pct=req.clutter_pct,
                    k=req.k_factor, grid=grid, georef=georef)
                warnings.extend(w for w in polar["warnings"] if w not in warnings)
                computed.append({"lat": s.lat, "lon": s.lon, "name": s.name,
                                 "radius_m": radius_m, "polar": polar})
    except jobs.SimBusyError as exc:
        raise HTTPException(429, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Coverage simulation failed: {exc}") from exc

    # Thermal noise floor for the co-channel SINR view.  Explicit request
    # fields win; else the preset's channel parameters; else a 10 MHz / 7 dB
    # generic receiver (flagged, so the assumption is visible).
    noise_dbm = None
    if req.interference and len(req.sites) > 1:
        bw = req.bandwidth_mhz or tech.get("bandwidth_mhz")
        nf = req.noise_figure_db if req.noise_figure_db is not None \
            else tech.get("noise_figure_db")
        if bw is None or nf is None:
            bw, nf = bw or 10.0, nf if nf is not None else 7.0
            warnings.append(
                f"SINR noise floor assumes a {bw:g} MHz / {nf:g} dB NF "
                "receiver (preset carries no channel parameters); set "
                "bandwidth_mhz / noise_figure_db to refine.")
        noise_dbm = -174.0 + 10.0 * float(np.log10(float(bw) * 1e6)) + float(nf)

    png, bounds, site_stats, served_frac, sinr = composite_best_server(
        computed, raster_px=req.raster_px, noise_dbm=noise_dbm)
    import uuid as _uuid
    result_id = _uuid.uuid4().hex[:12]
    results_store.save("coverage", result_id, png, {"bounds": bounds})

    sinr_out = None
    if sinr is not None:
        sinr_id = _uuid.uuid4().hex[:12]
        results_store.save("coverage", sinr_id, sinr.pop("png"),
                           {"bounds": bounds})
        sinr_out = {"png_url": f"/api/rf/coverage/{sinr_id}.png", **sinr}

    return {
        "coverage_id": result_id,
        "png_url": f"/api/rf/coverage/{result_id}.png",
        "bounds": bounds,
        "legend": [{"label": s["name"], "color": s["color"],
                    "margin_db": 0} for s in site_stats],
        "stats": {
            "sites": site_stats,
            "served_area_fraction": served_frac,
            "radius_m": radius_m,
            "tx_elevation_m": computed[0]["polar"]["tx_elev"],
            "max_rx_power_dbm": max(s["max_rx_power_dbm"] for s in site_stats),
        },
        "sinr": sinr_out,
        "technology": {**tech, "key": req.technology},
        "warnings": warnings,
    }


# ===================================================================== #
#  Phase 1 — Bidirectional "talk-back" LMR & repeater-system design
# ===================================================================== #
from ..services.rf import talkback as _talkback  # noqa: E402


@router.get("/portable-profiles")
def list_portable_profiles() -> dict:
    """Portable/mobile radio profiles for two-way LMR studies (body loss,
    1.5 m antenna height, building/vehicle penetration, device EIRP)."""
    return {"profiles": [{"key": k, **v}
                         for k, v in _talkback.PORTABLE_PROFILES.items()],
            "daq_ladder": [{"min_margin_db": m, "daq": d, "description": desc}
                           for m, d, desc in _talkback.DAQ_LADDER],
            "user_environments": ["on_street", "in_building", "in_vehicle"]}


class _TalkbackOverrides(BaseModel):
    freq_mhz: float | None = Field(None, gt=0)
    model: str | None = None
    environment: str | None = None
    tx_power_dbm: float | None = None
    tx_gain_dbi: float | None = None
    rx_gain_dbi: float | None = None
    losses_db: float | None = None
    rx_sensitivity_dbm: float | None = None
    h_bs_m: float | None = Field(None, gt=0)
    # Portable overrides (any PORTABLE_PROFILES field):
    portable_tx_power_dbm: float | None = None
    portable_antenna_gain_dbi: float | None = None
    portable_antenna_height_m: float | None = Field(None, gt=0)
    portable_body_loss_db: float | None = Field(None, ge=0, le=20)
    portable_building_penetration_db: float | None = Field(None, ge=0, le=40)
    portable_rx_sensitivity_dbm: float | None = None


def _resolve_talkback(technology: str, profile: str, ov: _TalkbackOverrides):
    """Build (base tech dict, portable dict) with request overrides applied."""
    try:
        tech = get_technology(technology)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for f in ("freq_mhz", "model", "environment", "tx_power_dbm", "tx_gain_dbi",
              "rx_gain_dbi", "losses_db", "rx_sensitivity_dbm", "h_bs_m"):
        v = getattr(ov, f)
        if v is not None:
            tech[f] = v
    if tech["model"] not in MODEL_INFO:
        raise HTTPException(422, f"Unknown propagation model: {tech['model']!r}")
    p_ov = {
        "tx_power_dbm": ov.portable_tx_power_dbm,
        "antenna_gain_dbi": ov.portable_antenna_gain_dbi,
        "antenna_height_m": ov.portable_antenna_height_m,
        "body_loss_db": ov.portable_body_loss_db,
        "building_penetration_db": ov.portable_building_penetration_db,
        "rx_sensitivity_dbm": ov.portable_rx_sensitivity_dbm,
    }
    try:
        portable = _talkback.get_portable_profile(profile, p_ov)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return tech, portable


class TalkbackRequest(_TalkbackOverrides):
    base_lat: float = Field(ge=-90, le=90)
    base_lon: float = Field(ge=-180, le=180)
    portable_lat: float = Field(ge=-90, le=90)
    portable_lon: float = Field(ge=-180, le=180)
    technology: str = "tetra400"
    portable_profile: str = "portable_handheld_5w"
    user_environment: str = "on_street"
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    foliage_depth_m: float = Field(0.0, ge=0, le=400)
    rain_rate_mm_h: float = Field(0.0, ge=0, le=150)
    clutter_pct: float = Field(0.0, ge=0, le=99.9)
    dxf_id: str | None = None
    surface: bool = False


@router.post("/talkback")
def talkback_link(req: TalkbackRequest,
                  user: dict | None = Depends(current_user)) -> dict:
    """Two-way LMR link between a base/repeater and a portable radio: computes
    talk-out (base->portable) and talk-in (portable->base) budgets over one
    reciprocal terrain path, grades each to TIA-4046 DAQ and returns the
    intersection (combined DAQ = min of the two directions)."""
    tech, portable = _resolve_talkback(req.technology, req.portable_profile, req)
    grid = georef = None
    if req.dxf_id:
        from .routes_dxf import resolve_dxf
        session = resolve_dxf(req.dxf_id, user)
        grid, georef = session.grid, session.georef
    fusion = resolve_fusion(req.surface)
    try:
        with jobs.sim_slot():
            res = _talkback.bidirectional_link(
                fusion, tech, portable,
                req.base_lat, req.base_lon, req.portable_lat, req.portable_lon,
                user_environment=req.user_environment, k=req.k_factor,
                foliage_depth_m=req.foliage_depth_m,
                rain_rate_mm_h=req.rain_rate_mm_h, clutter_pct=req.clutter_pct,
                grid=grid, georef=georef)
    except jobs.SimBusyError as exc:
        raise HTTPException(429, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Talk-back analysis failed: {exc}") from exc
    return {
        "base": {"lat": req.base_lat, "lon": req.base_lon},
        "portable": {"lat": req.portable_lat, "lon": req.portable_lon},
        "technology": {**tech, "key": req.technology},
        "portable_profile": {**portable, "key": req.portable_profile},
        "distance_m": res.distance_m,
        "path_loss_db": res.path_loss_db,
        "diffraction_loss_db": res.diffraction_loss_db,
        "environment_loss_db": res.environment_loss_db,
        "los_clear": res.los_clear,
        "talk_out": res.talk_out,
        "talk_in": res.talk_in,
        "combined": res.combined,
        "limiting_direction": res.limiting_direction,
        "warnings": res.warnings,
    }


class _TalkbackPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    name: str | None = None


class TalkbackBatchRequest(_TalkbackOverrides):
    base_lat: float = Field(ge=-90, le=90)
    base_lon: float = Field(ge=-180, le=180)
    portables: list[_TalkbackPoint] = Field(..., min_length=1, max_length=200)
    technology: str = "tetra400"
    portable_profile: str = "portable_handheld_5w"
    user_environment: str = "on_street"
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    foliage_depth_m: float = Field(0.0, ge=0, le=400)
    rain_rate_mm_h: float = Field(0.0, ge=0, le=150)
    clutter_pct: float = Field(0.0, ge=0, le=99.9)
    dxf_id: str | None = None
    surface: bool = False


@router.post("/talkback/batch")
def talkback_batch(req: TalkbackBatchRequest,
                   user: dict | None = Depends(current_user)) -> dict:
    """Grade up to 200 portable locations for two-way talk-back against one
    base/repeater — the LMR analogue of /batch, returning per-location DAQ
    for talk-out, talk-in and the combined (limiting) direction."""
    tech, portable = _resolve_talkback(req.technology, req.portable_profile, req)
    grid = georef = None
    if req.dxf_id:
        from .routes_dxf import resolve_dxf
        session = resolve_dxf(req.dxf_id, user)
        grid, georef = session.grid, session.georef
    fusion = resolve_fusion(req.surface)
    rows = []
    try:
        with jobs.sim_slot():
            for i, p in enumerate(req.portables):
                r = _talkback.bidirectional_link(
                    fusion, tech, portable,
                    req.base_lat, req.base_lon, p.lat, p.lon,
                    user_environment=req.user_environment, k=req.k_factor,
                    foliage_depth_m=req.foliage_depth_m,
                    rain_rate_mm_h=req.rain_rate_mm_h,
                    clutter_pct=req.clutter_pct, grid=grid, georef=georef)
                rows.append({
                    "name": p.name or f"P{i + 1}", "lat": p.lat, "lon": p.lon,
                    "distance_m": r.distance_m,
                    "talk_out_daq": r.talk_out["daq"],
                    "talk_in_daq": r.talk_in["daq"],
                    "combined_daq": r.combined["daq"],
                    "limiting_direction": r.limiting_direction,
                    "served": r.combined["served"]})
    except jobs.SimBusyError as exc:
        raise HTTPException(429, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Talk-back batch failed: {exc}") from exc
    served = sum(1 for r in rows if r["served"])
    return {
        "base": {"lat": req.base_lat, "lon": req.base_lon},
        "technology": {**tech, "key": req.technology},
        "portable_profile": {**portable, "key": req.portable_profile},
        "portables": rows,
        "summary": {"total": len(rows), "served": served,
                    "served_fraction": round(served / len(rows), 4)},
    }


class RepeaterDesignRequest(BaseModel):
    freq_mhz: float = Field(..., gt=0)
    system_gain_db: float = Field(..., ge=0, le=120)
    donor_coverage_separation_m: float = Field(..., gt=0, le=200)
    arrangement: str = Field("vertical", pattern="^(vertical|horizontal)$")
    stability_margin_db: float = Field(15.0, ge=0, le=40)
    tx_gain_dbi: float = 0.0
    rx_gain_dbi: float = 0.0
    reliable_range_m: float | None = Field(None, gt=0)
    overlap_fraction: float = Field(0.15, ge=0, le=0.5)


@router.post("/repeater/design")
def repeater_design(req: RepeaterDesignRequest) -> dict:
    """Repeater-system verdict: donor/coverage antenna isolation, the
    feedback-stable maximum gain (isolation - stability margin) and — when a
    reliable one-way range is given — the cascade spacing for continuous
    talk-back along a linear route (highway/rail/tunnel access)."""
    return _talkback.repeater_design(
        req.freq_mhz, req.system_gain_db, req.donor_coverage_separation_m,
        arrangement=req.arrangement, stability_margin_db=req.stability_margin_db,
        reliable_range_m=req.reliable_range_m, overlap_fraction=req.overlap_fraction,
        tx_gain_dbi=req.tx_gain_dbi, rx_gain_dbi=req.rx_gain_dbi)


# ===================================================================== #
#  Phase 5 — EMF compliance, ITM propagation, drive-test calibration
# ===================================================================== #
from fastapi import Query  # noqa: E402
from ..services.rf import emf as _emf  # noqa: E402
from ..services.rf import itm as _itm  # noqa: E402
from ..services.rf import calibration as _calib  # noqa: E402


class EmfRequest(BaseModel):
    technology: str | None = None
    freq_mhz: float | None = Field(None, gt=0)
    tx_power_dbm: float | None = None
    gain_dbi: float | None = None
    losses_db: float = Field(0.0, ge=0)
    mount_height_m: float = Field(15.0, gt=0, le=500)
    standard: str = Field("fcc", pattern="^(fcc|icnirp)$")
    reflection_factor: float = Field(2.56, ge=1.0, le=4.0)


@router.post("/emf-compliance")
def emf_compliance(req: EmfRequest) -> dict:
    """FCC OET-65 / ICNIRP RF-exposure compliance: MPE limits and the
    occupational vs public exclusion-zone distances (slant + ground extent)
    around a transmitter — the permitting deliverable."""
    freq = req.freq_mhz
    power = req.tx_power_dbm
    gain = req.gain_dbi
    if req.technology:
        try:
            tech = get_technology(req.technology)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        freq = freq if freq is not None else tech["freq_mhz"]
        power = power if power is not None else tech["tx_power_dbm"]
        gain = gain if gain is not None else tech["tx_gain_dbi"]
    if freq is None or power is None or gain is None:
        raise HTTPException(422, "Provide technology, or freq_mhz + "
                                 "tx_power_dbm + gain_dbi.")
    return _emf.exposure_zones(
        float(freq), float(power), float(gain), losses_db=req.losses_db,
        mount_height_m=req.mount_height_m, standard=req.standard,
        reflection_factor=req.reflection_factor)


class ItmRequest(BaseModel):
    lat1: float = Field(ge=-90, le=90)
    lon1: float = Field(ge=-180, le=180)
    lat2: float = Field(ge=-90, le=90)
    lon2: float = Field(ge=-180, le=180)
    freq_mhz: float = Field(900.0, gt=0)
    h_tx_m: float = Field(30.0, gt=0)
    h_rx_m: float = Field(1.5, gt=0)
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    dxf_id: str | None = None
    surface: bool = False
    samples: int = Field(256, ge=32, le=1024)


@router.post("/itm-profile")
def itm_profile(req: ItmRequest,
                user: dict | None = Depends(current_user)) -> dict:
    """Longley-Rice / ITM-family loss over the fused terrain profile, returned
    alongside the Deygout diffraction loss for the same path so the two
    methods can be compared directly."""
    grid = georef = None
    if req.dxf_id:
        from .routes_dxf import resolve_dxf
        session = resolve_dxf(req.dxf_id, user)
        grid, georef = session.grid, session.georef
    fusion = resolve_fusion(req.surface)
    try:
        with jobs.sim_slot():
            prof = fusion.profile(req.lat1, req.lon1, req.lat2, req.lon2,
                                  n_samples=req.samples, grid=grid, georef=georef)
            d, elev = prof.distances_m, prof.elevations_m
            itm_res = _itm.itm_point_to_point(
                d, elev, req.freq_mhz, req.h_tx_m, req.h_rx_m, k=req.k_factor)
            from ..services.rf.physics import apply_earth_curvature
            from ..services.rf.models import deygout_loss_db, fspl_db
            curved = apply_earth_curvature(d, elev, k=req.k_factor)
            deygout = float(deygout_loss_db(d, curved, req.h_tx_m, req.h_rx_m,
                                            req.freq_mhz))
            fspl = float(fspl_db(np.array([d[-1]]), req.freq_mhz)[0])
    except jobs.SimBusyError as exc:
        raise HTTPException(429, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"ITM study failed: {exc}") from exc
    return {
        "itm": itm_res,
        "deygout": {"model": "deygout", "free_space_db": round(fspl, 1),
                    "diffraction_db": round(deygout, 1),
                    "loss_db": round(fspl + deygout, 1)},
        "difference_db": round(itm_res["loss_db"] - (fspl + deygout), 1),
    }


class CalibrateMeasurement(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    measured_dbm: float


class CalibrateRequest(BaseModel):
    tx_lat: float = Field(ge=-90, le=90)
    tx_lon: float = Field(ge=-180, le=180)
    technology: str = "custom"
    measurements: list[CalibrateMeasurement] = Field(..., min_length=2, max_length=5000)
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    dxf_id: str | None = None
    surface: bool = False
    freq_mhz: float | None = Field(None, gt=0)
    model: str | None = None
    tx_power_dbm: float | None = None
    tx_gain_dbi: float | None = None
    h_bs_m: float | None = Field(None, gt=0)


def _predict_and_fit(req, rows, user):
    try:
        tech = get_technology(req.technology)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for f in ("freq_mhz", "model", "tx_power_dbm", "tx_gain_dbi", "h_bs_m"):
        v = getattr(req, f, None)
        if v is not None:
            tech[f] = v
    grid = georef = None
    if req.dxf_id:
        from .routes_dxf import resolve_dxf
        session = resolve_dxf(req.dxf_id, user)
        grid, georef = session.grid, session.georef
    from ..services.rf.planning import evaluate_receiver
    fusion = resolve_fusion(req.surface)
    predicted, measured, distances = [], [], []
    with jobs.sim_slot():
        for r in rows:
            res = evaluate_receiver(fusion, dict(tech), req.tx_lat, req.tx_lon,
                                    r["lat"], r["lon"], k=req.k_factor,
                                    grid=grid, georef=georef)
            predicted.append(res["rx_power_dbm"])
            measured.append(r["measured_dbm"])
            distances.append(res["distance_m"])
    fit = _calib.fit_correction(predicted, measured, distances)
    return {"technology": {**tech, "key": req.technology}, "calibration": fit}


@router.post("/calibrate")
def calibrate(req: CalibrateRequest,
              user: dict | None = Depends(current_user)) -> dict:
    """Fit an empirical model correction (offset + distance slope) from
    measured RSSI so predictions match reality; reports RMSE/MAE before/after."""
    rows = [{"lat": m.lat, "lon": m.lon, "measured_dbm": m.measured_dbm}
            for m in req.measurements]
    try:
        return _predict_and_fit(req, rows, user)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Calibration failed: {exc}") from exc


@router.post("/calibrate/upload")
async def calibrate_upload(
        tx_lat: float = Query(..., ge=-90, le=90),
        tx_lon: float = Query(..., ge=-180, le=180),
        technology: str = Query("custom"),
        k_factor: float = Query(4.0 / 3.0, gt=0.1, le=10),
        dxf_id: str | None = Query(None),
        file: UploadFile = File(...),
        user: dict | None = Depends(current_user)) -> dict:
    """Upload a drive-test CSV or GPX (lat, lon, RSSI) and fit the correction.
    CSV needs lat/lon/rssi columns; GPX reads RSSI from the point comment."""
    data = (await file.read()).decode("utf-8", errors="replace")
    name = (file.filename or "").lower()
    try:
        rows = _calib.parse_gpx(data) if name.endswith(".gpx") \
            else _calib.parse_csv(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if len(rows) < 2:
        raise HTTPException(422, "Need at least 2 measured points with lat, "
                                 "lon and RSSI.")

    class _Req:
        pass
    r = _Req()
    r.tx_lat, r.tx_lon, r.technology = tx_lat, tx_lon, technology
    r.k_factor, r.dxf_id, r.surface = k_factor, dxf_id, False
    r.freq_mhz = r.model = r.tx_power_dbm = r.tx_gain_dbi = r.h_bs_m = None
    try:
        result = _predict_and_fit(r, rows, user)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Calibration failed: {exc}") from exc
    result["points_used"] = len(rows)
    return result
