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


class CalibrationIn(BaseModel):
    """A drive-test fit (from /api/rf/calibrate) applied to a study —
    the closed calibration loop: fit once, run site-tuned studies after."""
    mode: str = Field("offset", pattern="^(offset|offset_slope)$")
    offset_db: float = Field(0.0, ge=-40, le=40)
    slope_intercept_db: float = Field(0.0, ge=-40, le=40)
    slope_per_decade_db: float = Field(0.0, ge=-30, le=30)


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
    # Per-pixel clutter: "worldcover" raises the obstacle surface by the real
    # land cover's representative height (ESA WorldCover 10 m, free).
    clutter_source: str = "none"
    # Simulate on the surface model (DSM) instead of bare terrain;
    # requires AM_DSM_URL to be configured on the server.
    surface: bool = False
    # Drive-test calibration correction (from /api/rf/calibrate's fit):
    calibration: CalibrationIn | None = None
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


def _clutter_fn(source: str):
    """Resolve a clutter_source string to a heights function (or None)."""
    if source == "worldcover":
        from ..services.clutter.worldcover import get_worldcover_store
        store = get_worldcover_store()
        return store.heights
    if source not in ("none", "", None):
        raise HTTPException(422, f"Unknown clutter_source: {source!r}")
    return None


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

    clutter_fn = _clutter_fn(getattr(req, "clutter_source", "none"))

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
            calibration=req.calibration.model_dump() if req.calibration else None,
            clutter_heights_fn=clutter_fn,
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


# -------------------------------------------------------- EMF compliance
class ComplianceRequest(BaseModel):
    freq_mhz: float = Field(gt=0)
    tx_power_dbm: float = Field(ge=-30, le=90)
    antenna_gain_dbi: float = Field(ge=-10, le=60)
    losses_db: float = Field(0.0, ge=0, le=30)
    ground_reflection: bool = False
    standard: str = Field("icnirp")
    assess_distance_m: float | None = Field(None, gt=0, le=10_000)


@router.post("/compliance")
def emf_compliance(req: ComplianceRequest) -> dict:
    """RF-exposure (EMF) compliance: ICNIRP or FCC OET-65 public/occupational
    exclusion-zone distances for an antenna - the permitting gate."""
    if req.standard.lower() not in ("icnirp", "fcc"):
        raise HTTPException(422, "standard must be 'icnirp' or 'fcc'")
    from ..services.rf.compliance import assess_exposure
    return assess_exposure(
        req.freq_mhz, req.tx_power_dbm, req.antenna_gain_dbi,
        losses_db=req.losses_db, ground_reflection=req.ground_reflection,
        standard=req.standard, assess_distance_m=req.assess_distance_m)


class EmfAntennaIn(BaseModel):
    label: str = Field("Antenna", max_length=60)
    freq_mhz: float = Field(gt=0)
    tx_power_dbm: float = Field(ge=-30, le=90)
    antenna_gain_dbi: float = Field(ge=-10, le=60)
    losses_db: float = Field(0.0, ge=0, le=30)


class EmfReportRequest(BaseModel):
    site: dict = Field(default_factory=dict)
    antennas: list[EmfAntennaIn] = Field(min_length=1, max_length=24)
    standard: str = "icnirp"
    ground_reflection: bool = True


@router.post("/compliance/report.pdf")
def emf_report(req: EmfReportRequest,
               user: dict | None = Depends(current_user)) -> Response:
    """Ready-to-file EMF dossier: per-antenna ICNIRP/FCC assessment, exclusion
    -zone summary, method statement and signature blocks — one click from the
    site data to the document the permitting authority expects."""
    if req.standard.lower() not in ("icnirp", "fcc"):
        raise HTTPException(422, "standard must be 'icnirp' or 'fcc'")
    from ..services.saas.compliance_report import build_emf_report
    pdf = build_emf_report(req.site, [a.model_dump() for a in req.antennas],
                           standard=req.standard,
                           ground_reflection=req.ground_reflection)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition":
                             'attachment; filename="emf-compliance.pdf"'})


# --------------------------------------------------- drive-test calibration
class MeasurementIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    rssi_dbm: float = Field(le=0)


class CalibrateRequest(BaseModel):
    tx_lat: float = Field(ge=-90, le=90)
    tx_lon: float = Field(ge=-180, le=180)
    technology: str = "custom"
    points: list[MeasurementIn] = Field(min_length=2, max_length=2000)
    dxf_id: str | None = None
    surface: bool = False
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    # Link-budget overrides (same semantics as /coverage):
    freq_mhz: float | None = Field(None, gt=0)
    model: str | None = None
    environment: str | None = None
    tx_power_dbm: float | None = None
    tx_gain_dbi: float | None = None
    rx_gain_dbi: float | None = None
    losses_db: float | None = None
    h_bs_m: float | None = Field(None, gt=0)
    h_ut_m: float | None = Field(None, gt=0)


@router.post("/calibrate")
def calibrate(req: CalibrateRequest,
              user: dict | None = Depends(current_user)) -> dict:
    """Fit a model correction (offset / offset+slope) from measured RSSI vs
    prediction and report RMS error before/after - turning predictions into
    calibrated, site-tuned predictions."""
    try:
        tech = get_technology(req.technology)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for f in ("freq_mhz", "model", "environment", "tx_power_dbm", "tx_gain_dbi",
              "rx_gain_dbi", "losses_db", "h_bs_m", "h_ut_m"):
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

    from ..services.rf.calibration import calibrate_drive_test
    try:
        with jobs.sim_slot():
            result = calibrate_drive_test(
                resolve_fusion(req.surface), tech, req.tx_lat, req.tx_lon,
                [p.model_dump() for p in req.points], k=req.k_factor,
                grid=grid, georef=georef)
            fit = result["fit"]
            # Ready-to-apply correction: POST this object back as the
            # "calibration" field of /coverage to run site-tuned studies.
            result["calibration"] = {
                "mode": fit["recommended"],
                "offset_db": fit["offset_db"],
                "slope_intercept_db": fit["slope_intercept_db"],
                "slope_per_decade_db": fit["slope_per_decade_db"],
            }
            return result
    except jobs.SimBusyError as exc:
        raise HTTPException(429, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Calibration failed: {exc}") from exc


# ------------------------------------------------ frequency / PCI planning
class SiteIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    name: str | None = None
    antenna_azimuth_deg: float | None = Field(None, ge=0, lt=360)
    downtilt_deg: float = Field(0.0, ge=-10, le=20)


class FrequencyPlanRequest(BaseModel):
    sites: list[SiteIn] = Field(min_length=2, max_length=24)
    technology: str = "custom"
    radius_km: float = Field(10.0, gt=0.1, le=150.0)
    n_channels: int = Field(3, ge=2, le=12)
    aci_db: float = Field(30.0, ge=10, le=60)     # adjacent-channel rejection
    with_pci: bool = True
    bandwidth_mhz: float | None = Field(None, gt=0, le=400)
    noise_figure_db: float | None = Field(None, ge=0, le=20)
    n_radials: int = Field(72, ge=36, le=360)
    n_steps: int = Field(48, ge=20, le=200)
    grid_n: int = Field(128, ge=48, le=256)
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    clutter_source: str = "none"
    surface: bool = False
    freq_mhz: float | None = Field(None, gt=0)
    model: str | None = None
    environment: str | None = None
    tx_power_dbm: float | None = None
    tx_gain_dbi: float | None = None
    h_bs_m: float | None = Field(None, gt=0)
    h_ut_m: float | None = Field(None, gt=0)


@router.post("/frequency-plan")
def frequency_plan(req: FrequencyPlanRequest,
                   user: dict | None = Depends(current_user)) -> dict:
    """Automatic channel + PCI plan over a site cluster: geometry-derived
    interference matrix -> weighted graph colouring -> post-plan SINR vs the
    reuse-1 baseline, so the gain of the plan is explicit."""
    require_feature(user, "multi_site")
    check_preset_allowed(user, req.technology)
    try:
        tech = get_technology(req.technology)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for f in ("freq_mhz", "model", "environment", "tx_power_dbm",
              "tx_gain_dbi", "h_bs_m", "h_ut_m"):
        v = getattr(req, f)
        if v is not None:
            tech[f] = v
    if tech["model"] not in MODEL_INFO:
        raise HTTPException(422, f"Unknown propagation model: {tech['model']!r}")

    clutter_fn = _clutter_fn(req.clutter_source)
    engine = CoverageEngine(resolve_fusion(req.surface))
    radius_m = req.radius_km * 1000.0
    computed = []
    try:
        with jobs.sim_slot():
            for s in req.sites:
                polar = engine.compute_polar(
                    s.lat, s.lon, dict(tech), radius_m=radius_m,
                    n_radials=req.n_radials, n_steps=req.n_steps,
                    antenna_azimuth_deg=s.antenna_azimuth_deg,
                    downtilt_deg=s.downtilt_deg, k=req.k_factor,
                    clutter_heights_fn=clutter_fn)
                computed.append({"lat": s.lat, "lon": s.lon, "name": s.name,
                                 "radius_m": radius_m, "polar": polar})
    except jobs.SimBusyError as exc:
        raise HTTPException(429, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Coverage simulation failed: {exc}") from exc

    bw = req.bandwidth_mhz or tech.get("bandwidth_mhz") or 10.0
    nf = req.noise_figure_db if req.noise_figure_db is not None \
        else tech.get("noise_figure_db", 7.0)
    noise_dbm = -174.0 + 10.0 * float(np.log10(float(bw) * 1e6)) + float(nf)

    from ..services.rf.freqplan import plan_frequencies
    result = plan_frequencies(computed, req.n_channels, noise_dbm,
                              aci_db=req.aci_db, with_pci=req.with_pci,
                              grid_n=req.grid_n)
    return {**result, "technology": {**tech, "key": req.technology},
            "noise_floor_dbm": round(noise_dbm, 1)}


# ------------------------------------------------------ capacity & traffic
@router.get("/erlang")
def erlang(traffic_erlangs: float, channels: int | None = None,
           gos: float | None = None, kind: str = "b") -> dict:
    """Erlang B/C dimensioning: blocking for N channels, and/or the channel
    count a grade of service requires (PMR/TETRA/trunked voice)."""
    from ..services.rf.capacity import channels_for_gos, erlang_b, erlang_c
    if kind not in ("b", "c"):
        raise HTTPException(422, "kind must be 'b' or 'c'")
    if traffic_erlangs < 0 or traffic_erlangs > 10_000:
        raise HTTPException(422, "traffic_erlangs out of range")
    out: dict = {"traffic_erlangs": traffic_erlangs, "kind": kind}
    fn = erlang_b if kind == "b" else erlang_c
    if channels is not None:
        if not (0 <= channels <= 10_000):
            raise HTTPException(422, "channels out of range")
        out["blocking_probability"] = round(fn(traffic_erlangs, channels), 5)
        out["channels"] = channels
    if gos is not None:
        if not (0 < gos < 1):
            raise HTTPException(422, "gos must be in (0,1)")
        try:
            out["channels_for_gos"] = channels_for_gos(traffic_erlangs, gos, kind)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        out["gos"] = gos
    return out


class ThroughputMapRequest(BaseModel):
    sites: list[SiteIn] = Field(min_length=1, max_length=24)
    technology: str = "custom"
    radius_km: float = Field(10.0, gt=0.1, le=150.0)
    bandwidth_mhz: float | None = Field(None, gt=0, le=400)
    noise_figure_db: float | None = Field(None, ge=0, le=20)
    overhead: float = Field(0.25, ge=0, lt=1)
    # Demand layer for the saturation verdict:
    users_per_cell: int = Field(0, ge=0, le=1_000_000)
    mbps_per_user: float = Field(0.0, ge=0, le=1000)
    # Optional frequency plan (from /frequency-plan) applied before SINR:
    channels: list[int] | None = None
    aci_db: float = Field(30.0, ge=10, le=60)
    render: bool = True          # also produce the Mbit/s heatmap overlay
    raster_px: int = Field(768, ge=128, le=2048)
    n_radials: int = Field(72, ge=36, le=360)
    n_steps: int = Field(48, ge=20, le=200)
    grid_n: int = Field(128, ge=48, le=256)
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    clutter_source: str = "none"
    surface: bool = False
    freq_mhz: float | None = Field(None, gt=0)
    model: str | None = None
    environment: str | None = None
    tx_power_dbm: float | None = None
    tx_gain_dbi: float | None = None
    h_bs_m: float | None = Field(None, gt=0)
    h_ut_m: float | None = Field(None, gt=0)


@router.post("/throughput-map")
def throughput_map(req: ThroughputMapRequest,
                   user: dict | None = Depends(current_user)) -> dict:
    """Per-cell capacity from the SINR field (3GPP CQI ladder), with a
    users×demand saturation verdict per cell — coverage AND capacity."""
    require_feature(user, "multi_site")
    check_preset_allowed(user, req.technology)
    try:
        tech = get_technology(req.technology)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for f in ("freq_mhz", "model", "environment", "tx_power_dbm",
              "tx_gain_dbi", "h_bs_m", "h_ut_m"):
        v = getattr(req, f)
        if v is not None:
            tech[f] = v
    if tech["model"] not in MODEL_INFO:
        raise HTTPException(422, f"Unknown propagation model: {tech['model']!r}")
    if req.channels is not None and len(req.channels) != len(req.sites):
        raise HTTPException(422, "channels must have one entry per site")

    clutter_fn = _clutter_fn(req.clutter_source)
    engine = CoverageEngine(resolve_fusion(req.surface))
    radius_m = req.radius_km * 1000.0
    computed = []
    try:
        with jobs.sim_slot():
            for s in req.sites:
                polar = engine.compute_polar(
                    s.lat, s.lon, dict(tech), radius_m=radius_m,
                    n_radials=req.n_radials, n_steps=req.n_steps,
                    antenna_azimuth_deg=s.antenna_azimuth_deg,
                    downtilt_deg=s.downtilt_deg, k=req.k_factor,
                    clutter_heights_fn=clutter_fn)
                computed.append({"lat": s.lat, "lon": s.lon, "name": s.name,
                                 "radius_m": radius_m, "polar": polar})
    except jobs.SimBusyError as exc:
        raise HTTPException(429, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Coverage simulation failed: {exc}") from exc

    bw = req.bandwidth_mhz or tech.get("bandwidth_mhz") or 10.0
    nf = req.noise_figure_db if req.noise_figure_db is not None \
        else tech.get("noise_figure_db", 7.0)
    noise_dbm = -174.0 + 10.0 * float(np.log10(float(bw) * 1e6)) + float(nf)

    from ..services.rf.capacity import cell_capacity, saturation
    from ..services.rf.freqplan import build_fields
    fields, best, covered = build_fields(computed, grid_n=req.grid_n)
    lin = np.where(np.isfinite(fields), 10.0 ** (fields / 10.0), 0.0)
    noise = 10.0 ** (noise_dbm / 10.0)
    aci = 10.0 ** (-req.aci_db / 10.0)

    cells = []
    for i in range(len(computed)):
        mask = (best == i) & covered
        S = lin[i]
        I = np.zeros_like(S)
        for j in range(len(computed)):
            if j == i:
                continue
            if req.channels is None or req.channels[j] == req.channels[i]:
                I += lin[j]
            elif abs(req.channels[j] - req.channels[i]) == 1:
                I += lin[j] * aci
        with np.errstate(divide="ignore", invalid="ignore"):
            sinr_db = 10.0 * np.log10(S / (I + noise))
        cap = cell_capacity(sinr_db, mask, float(bw), req.overhead)
        entry = {"site": computed[i].get("name") or f"Site {i + 1}",
                 "lat": computed[i]["lat"], "lon": computed[i]["lon"], **cap}
        if req.users_per_cell and req.mbps_per_user:
            entry["saturation"] = saturation(cap["capacity_mbps"],
                                             req.users_per_cell,
                                             req.mbps_per_user)
        cells.append(entry)

    out = {"cells": cells, "bandwidth_mhz": float(bw),
           "noise_floor_dbm": round(noise_dbm, 1),
           "overhead": req.overhead,
           "plan_applied": req.channels is not None,
           "technology": {**tech, "key": req.technology}}

    if req.render:
        from ..services.terrain.coverage import composite_throughput
        png, bounds, legend, tstats = composite_throughput(
            computed, noise_dbm, float(bw), overhead=req.overhead,
            channels=req.channels, aci_db=req.aci_db,
            raster_px=req.raster_px)
        import uuid as _uuid
        result_id = _uuid.uuid4().hex[:12]
        results_store.save("coverage", result_id, png, {"bounds": bounds})
        out.update({"png_url": f"/api/rf/coverage/{result_id}.png",
                    "bounds": bounds, "legend": legend,
                    "raster_stats": tstats})
    return out


class MonteCarloRequest(ThroughputMapRequest):
    # Traffic snapshots: total users dropped over the served area per draw.
    users: int = Field(200, ge=1, le=5000)
    demand_mbps: float = Field(2.0, gt=0, le=1000)
    draws: int = Field(100, ge=1, le=500)
    seed: int = Field(1, ge=0, le=2**31 - 1)


@router.post("/montecarlo")
def montecarlo_traffic(req: MonteCarloRequest,
                       user: dict | None = Depends(current_user)) -> dict:
    """Monte Carlo traffic snapshots over the cluster: random user drops,
    best-server attachment, equal-airtime scheduling — satisfied-user
    fraction with confidence bounds instead of a single saturation number."""
    require_feature(user, "multi_site")
    check_preset_allowed(user, req.technology)
    try:
        tech = get_technology(req.technology)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for f in ("freq_mhz", "model", "environment", "tx_power_dbm",
              "tx_gain_dbi", "h_bs_m", "h_ut_m"):
        v = getattr(req, f)
        if v is not None:
            tech[f] = v
    if tech["model"] not in MODEL_INFO:
        raise HTTPException(422, f"Unknown propagation model: {tech['model']!r}")
    if req.channels is not None and len(req.channels) != len(req.sites):
        raise HTTPException(422, "channels must have one entry per site")

    clutter_fn = _clutter_fn(req.clutter_source)
    engine = CoverageEngine(resolve_fusion(req.surface))
    radius_m = req.radius_km * 1000.0
    computed = []
    try:
        with jobs.sim_slot():
            for s in req.sites:
                polar = engine.compute_polar(
                    s.lat, s.lon, dict(tech), radius_m=radius_m,
                    n_radials=req.n_radials, n_steps=req.n_steps,
                    antenna_azimuth_deg=s.antenna_azimuth_deg,
                    downtilt_deg=s.downtilt_deg, k=req.k_factor,
                    clutter_heights_fn=clutter_fn)
                computed.append({"lat": s.lat, "lon": s.lon, "name": s.name,
                                 "radius_m": radius_m, "polar": polar})
    except jobs.SimBusyError as exc:
        raise HTTPException(429, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Coverage simulation failed: {exc}") from exc

    bw = req.bandwidth_mhz or tech.get("bandwidth_mhz") or 10.0
    nf = req.noise_figure_db if req.noise_figure_db is not None \
        else tech.get("noise_figure_db", 7.0)
    noise_dbm = -174.0 + 10.0 * float(np.log10(float(bw) * 1e6)) + float(nf)

    from ..services.rf.montecarlo import simulate_traffic
    try:
        result = simulate_traffic(
            computed, req.users, req.demand_mbps, noise_dbm, float(bw),
            draws=req.draws, overhead=req.overhead, channels=req.channels,
            aci_db=req.aci_db, grid_n=req.grid_n, seed=req.seed)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {**result, "bandwidth_mhz": float(bw),
            "noise_floor_dbm": round(noise_dbm, 1),
            "technology": {**tech, "key": req.technology}}


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
class MultiCoverageRequest(BaseModel):
    sites: list[SiteIn] = Field(min_length=1, max_length=24)
    technology: str = "custom"
    radius_km: float = Field(10.0, gt=0.1, le=150.0)
    dxf_id: str | None = None
    antenna_id: str | None = None
    antenna_beamwidth_deg: float = Field(65.0, gt=5, le=360)
    shadow_margin_db: float = Field(0.0, ge=0, le=30)
    foliage_depth_m: float = Field(0.0, ge=0, le=400)
    rain_rate_mm_h: float = Field(0.0, ge=0, le=150)
    clutter_pct: float = Field(0.0, ge=0, le=99.9)
    clutter_source: str = "none"
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

    clutter_fn = _clutter_fn(req.clutter_source)
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
                    k=req.k_factor, grid=grid, georef=georef,
                    clutter_heights_fn=clutter_fn)
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
