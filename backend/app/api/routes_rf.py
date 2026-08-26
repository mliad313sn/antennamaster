"""RF study endpoints: technology presets, propagation models, area coverage."""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..services import results_store
from ..services.rf import antenna as antenna_store
from ..services.rf.models import MODEL_INFO
from ..services.rf.technologies import TECHNOLOGIES, get_technology
from ..services.saas import jobs
from ..services.saas.tiers import check_preset_allowed, require_feature
from ..services.terrain import coverage as coverage_mod
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
    # `stats` is persisted so every downstream artifact (PDF, exports) can read
    # the figures the ENGINE produced instead of trusting a caller-supplied
    # number -- a rendered document must never be able to disagree with its map.
    results_store.save("coverage", result.coverage_id, result.png,
                       {"bounds": result.bounds,
                        "tx_lat": req.lat, "tx_lon": req.lon,
                        "radius_m": req.radius_km * 1000.0,
                        "stats": result.stats,
                        # Owner-scopes every read of this raster
                        # (see resolve_result).
                        "owner_id": user["id"] if user else None})
    # Numeric field sidecar so /at can report the level behind any pixel.
    if result.polar is not None:
        results_store.save_field(
            "coverage", result.coverage_id,
            az=result.polar["az"], dist=result.polar["dist"],
            margin=result.polar["margin"], rx_power=result.polar["rx_power"])

    return {
        "coverage_id": result.coverage_id,
        "png_url": f"/api/rf/coverage/{result.coverage_id}.png",
        "bounds": result.bounds,
        "legend": result.legend,
        "stats": result.stats,
        "technology": {**tech, "key": req.technology},
        "warnings": result.warnings,
    }


def resolve_result(coverage_id: str, user: dict | None,
                   kind: str = "coverage") -> tuple[bytes, dict]:
    """Load a stored raster, owner-scoped.

    A result id is not a capability.  It travels in share links, exported PDF
    footers, audit detail fields and reverse-proxy logs, so treating knowledge
    of a 12-hex id as authorisation leaked other tenants' georeferenced site
    footprints through .png/.tif/.kmz and the /at point query -- confidential
    infrastructure locations for mobile operators, mines and public-safety
    networks.  Mirrors ``resolve_dxf``: results with no owner (the anonymous
    self-hosted default) stay open, and someone else's result answers 404
    rather than 403 so the id is not an existence oracle.
    """
    hit = results_store.load(kind, coverage_id)
    if hit is None:
        raise HTTPException(404, "Coverage result expired or unknown")
    owner = (hit[1] or {}).get("owner_id")
    if owner is not None and (user is None or user.get("id") != owner):
        raise HTTPException(404, "Coverage result expired or unknown")
    return hit


@router.get("/coverage/{coverage_id}/at")
def coverage_point(coverage_id: str,
                   lat: float = Query(..., ge=-90, le=90),
                   lon: float = Query(..., ge=-180, le=180),
                   user: dict | None = Depends(current_user)) -> dict:
    """Predicted level at one point of an existing coverage study.

    A raster shows the class of every pixel but not its value; planners need
    to read the actual dBm at a candidate address without re-running a study.
    The answer is looked up out of the stored polar field with the same
    indexing that painted the raster, so number and colour always agree.
    """
    hit = resolve_result(coverage_id, user)
    field = results_store.load_field("coverage", coverage_id)
    if field is None:
        raise HTTPException(
            409, "This study predates point queries - re-run it to inspect points")
    meta = hit[1]
    return coverage_mod.point_value(
        field["az"], field["dist"], field["margin"], field["rx_power"],
        tx_lat=float(meta["tx_lat"]), tx_lon=float(meta["tx_lon"]),
        radius_m=float(meta["radius_m"]), lat=lat, lon=lon)


@router.get("/coverage/{coverage_id}.png")
def coverage_png(coverage_id: str,
                 user: dict | None = Depends(current_user)) -> Response:
    hit = resolve_result(coverage_id, user)
    return Response(content=hit[0], media_type="image/png",
                    headers={"Cache-Control": "max-age=3600"})


@router.get("/coverage/{coverage_id}.tif")
def coverage_geotiff(coverage_id: str,
                     band: str | None = Query(
                         None, pattern="^(rx_power|margin)$",
                         description="Export physical values as a single-band "
                                     "Float32 raster instead of the coloured "
                                     "picture: rx_power (dBm) or margin (dB)."),
                     user: dict | None = Depends(current_user)) -> Response:
    """Coverage raster as a georeferenced GeoTIFF (EPSG:4326) - the GIS-native
    format ArcGIS/QGIS/Atoll/Pathloss import directly, unlike a bare PNG.

    Without ``band`` this is the coloured RGBA overlay: a *picture*, five
    hard-coded margin classes at 8 bits.  With ``band`` it is the DATA the
    picture was drawn from - one Float32 band of dBm or dB, NaN beyond the
    study radius and declared as nodata - which is what a GIS team needs to
    threshold at their own level, reclassify, or intersect with a demand
    layer.  The default is unchanged so existing links keep working.
    """
    png, meta = resolve_result(coverage_id, user)
    bounds = meta.get("bounds", [[0, 0], [0, 0]])

    if band:
        field = results_store.load_field("coverage", coverage_id)
        if field is None:
            raise HTTPException(
                409, "This study predates numeric export - re-run it to get "
                     "a data GeoTIFF (the coloured raster is still available "
                     "without the band parameter).")
        for key in ("tx_lat", "tx_lon", "radius_m"):
            if key not in meta:
                raise HTTPException(
                    409, "This study has no stored geometry - re-run it to "
                         "export the numeric field.")
        from PIL import Image as _Image
        import io as _io
        with _Image.open(_io.BytesIO(png)) as im:
            px = im.size[0]
        grid, fbounds = coverage_mod.resample_field(
            field["az"], field["dist"], field[band],
            tx_lat=float(meta["tx_lat"]), tx_lon=float(meta["tx_lon"]),
            radius_m=float(meta["radius_m"]), px=px)
        from ..services.geotiff import field_to_geotiff
        return Response(
            content=field_to_geotiff(grid, fbounds), media_type="image/tiff",
            headers={"Content-Disposition":
                     f'attachment; filename="coverage-{coverage_id}-{band}.tif"'})

    from ..services.geotiff import rgba_png_to_geotiff
    tif = rgba_png_to_geotiff(png, bounds)
    return Response(
        content=tif, media_type="image/tiff",
        headers={"Content-Disposition":
                 f'attachment; filename="coverage-{coverage_id}.tif"'})


@router.get("/coverage/{coverage_id}.kmz")
def coverage_kmz(coverage_id: str,
                 user: dict | None = Depends(current_user)) -> Response:
    """Coverage raster as a KMZ GroundOverlay - opens in Google Earth / GIS,
    the deliverable format planners hand to clients."""
    png, meta = resolve_result(coverage_id, user)
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
    """One transmitter in a cluster study.

    Every field below ``downtilt_deg`` is a PER-SITE radio parameter. Without
    them a cluster study cloned one technology dict across every site, so a
    real network - an 800 MHz macro layer, a 3.5 GHz capacity layer and a
    400 MHz PMR overlay, each with its own power, mast height and antenna -
    simply could not be expressed, and the composite described a network that
    does not exist. Anything left ``None`` falls back to the request-level
    value, which in turn falls back to the technology preset, so an existing
    caller that sends only lat/lon/name behaves exactly as before.
    """
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    name: str | None = None
    antenna_azimuth_deg: float | None = Field(None, ge=0, lt=360)
    downtilt_deg: float = Field(0.0, ge=-10, le=20)
    # --- per-site radio parameters (None = inherit) ---------------------
    freq_mhz: float | None = Field(None, gt=0)
    tx_power_dbm: float | None = None
    tx_gain_dbi: float | None = None
    rx_gain_dbi: float | None = None
    losses_db: float | None = None
    rx_sensitivity_dbm: float | None = None
    h_bs_m: float | None = Field(None, gt=0)
    h_ut_m: float | None = Field(None, gt=0)
    antenna_beamwidth_deg: float | None = Field(None, gt=5, le=360)


# The per-site fields that override the cluster-wide technology dict.
_SITE_RADIO_FIELDS = (
    "freq_mhz", "tx_power_dbm", "tx_gain_dbi", "rx_gain_dbi", "losses_db",
    "rx_sensitivity_dbm", "h_bs_m", "h_ut_m",
)


def site_tech(base: dict, site: SiteIn) -> dict:
    """The technology dict this particular transmitter actually runs on.

    Resolution order: the site's own value, else whatever the request already
    resolved (preset + request-level overrides). Returns a copy, so sites
    never share mutable state.
    """
    tech = dict(base)
    for f in _SITE_RADIO_FIELDS:
        v = getattr(site, f, None)
        if v is not None:
            tech[f] = v
    return tech


def site_echo(site: SiteIn, tech: dict) -> dict:
    """What was actually used for this site, echoed back to the caller.

    A cluster study is only auditable if the response says which numbers each
    transmitter ran on - otherwise a per-site override is indistinguishable
    from a silently ignored one.
    """
    return {
        "name": site.name,
        "lat": site.lat, "lon": site.lon,
        "antenna_azimuth_deg": site.antenna_azimuth_deg,
        "downtilt_deg": site.downtilt_deg,
        **{f: tech.get(f) for f in _SITE_RADIO_FIELDS},
    }


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
                st = site_tech(tech, s)
                polar = engine.compute_polar(
                    s.lat, s.lon, st, radius_m=radius_m,
                    n_radials=req.n_radials, n_steps=req.n_steps,
                    antenna_azimuth_deg=s.antenna_azimuth_deg,
                    # Only the multi-coverage request carries a cluster-wide
                    # beamwidth; the planning endpoints fall back to the
                    # engine default rather than inventing an attribute.
                    antenna_beamwidth_deg=(
                        s.antenna_beamwidth_deg
                        if s.antenna_beamwidth_deg is not None
                        else getattr(req, "antenna_beamwidth_deg", 65.0)),
                    downtilt_deg=s.downtilt_deg, k=req.k_factor,
                    clutter_heights_fn=clutter_fn)
                computed.append({"lat": s.lat, "lon": s.lon, "name": s.name,
                                 "radius_m": radius_m, "polar": polar,
                                 "resolved": site_echo(s, st)})
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
                st = site_tech(tech, s)
                polar = engine.compute_polar(
                    s.lat, s.lon, st, radius_m=radius_m,
                    n_radials=req.n_radials, n_steps=req.n_steps,
                    antenna_azimuth_deg=s.antenna_azimuth_deg,
                    # Only the multi-coverage request carries a cluster-wide
                    # beamwidth; the planning endpoints fall back to the
                    # engine default rather than inventing an attribute.
                    antenna_beamwidth_deg=(
                        s.antenna_beamwidth_deg
                        if s.antenna_beamwidth_deg is not None
                        else getattr(req, "antenna_beamwidth_deg", 65.0)),
                    downtilt_deg=s.downtilt_deg, k=req.k_factor,
                    clutter_heights_fn=clutter_fn)
                computed.append({"lat": s.lat, "lon": s.lon, "name": s.name,
                                 "radius_m": radius_m, "polar": polar,
                                 "resolved": site_echo(s, st)})
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
        results_store.save("coverage", result_id, png, {
            "bounds": bounds,
            "owner_id": user["id"] if user else None})
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
                st = site_tech(tech, s)
                polar = engine.compute_polar(
                    s.lat, s.lon, st, radius_m=radius_m,
                    n_radials=req.n_radials, n_steps=req.n_steps,
                    antenna_azimuth_deg=s.antenna_azimuth_deg,
                    # Only the multi-coverage request carries a cluster-wide
                    # beamwidth; the planning endpoints fall back to the
                    # engine default rather than inventing an attribute.
                    antenna_beamwidth_deg=(
                        s.antenna_beamwidth_deg
                        if s.antenna_beamwidth_deg is not None
                        else getattr(req, "antenna_beamwidth_deg", 65.0)),
                    downtilt_deg=s.downtilt_deg, k=req.k_factor,
                    clutter_heights_fn=clutter_fn)
                computed.append({"lat": s.lat, "lon": s.lon, "name": s.name,
                                 "radius_m": radius_m, "polar": polar,
                                 "resolved": site_echo(s, st)})
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


def _sanitize_receiver_row(row: dict) -> dict:
    """Keep one un-evaluable receiver from taking down an entire batch.

    A pasted subscriber list routinely contains the tower itself, a duplicate
    row, or a CPE at the mast.  A zero-length path has no free-space loss
    (20*log10(0)) and no line to diffract over, so the link budget comes back
    non-finite -- which used to raise straight through the endpoint and 500
    the whole request, losing the 199 good rows with it.  Such a row is now
    reported with null figures, ``served`` null (neither served nor unserved:
    unknown) and a note saying why, so the operator can see and fix the input.
    """
    import math
    bad = [k for k, v in row.items()
           if isinstance(v, float) and not math.isfinite(v)]
    if not bad:
        row.setdefault("note", None)
        return row
    # Null every DERIVED figure, not just the non-finite ones: a link budget
    # built on a degenerate geometry is meaningless even where it happens to
    # come out finite, and printing "margin 100.0 dB" next to "not evaluable"
    # invites exactly the misreading this row is meant to prevent.  Identity
    # and geometry (name, lat, lon, distance) are kept so the operator can
    # find the offending input.
    derived = ("rx_power_dbm", "margin_db", "path_loss_db",
               "diffraction_loss_db", "environment_loss_db",
               "fresnel_clearance_ratio", "los_clear")
    out = {k: (None if (k in derived
                        or (isinstance(v, float) and not math.isfinite(v)))
               else v)
           for k, v in row.items()}
    dist = row.get("distance_m")
    if isinstance(dist, float) and math.isfinite(dist) and dist < 1.0:
        why = ("receiver is co-located with the transmitter "
               "(zero-length path); move it or drop the row")
    else:
        why = ("path could not be evaluated at this geometry "
               f"(non-finite: {', '.join(sorted(bad))})")
    out["served"] = None
    out["note"] = f"Not evaluable: {why}."
    return out


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
                rows.append(_sanitize_receiver_row(
                    {"name": r.name or f"RX {i + 1}",
                     "lat": r.lat, "lon": r.lon, **res}))
    except jobs.SimBusyError as exc:
        raise HTTPException(429, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Batch analysis failed: {exc}") from exc

    served = sum(1 for r in rows if r["served"])
    if format == "csv":
        header = ["name", "lat", "lon", "distance_m", "rx_power_dbm",
                  "margin_db", "served", "los_clear",
                  "fresnel_clearance_ratio", "path_loss_db",
                  "diffraction_loss_db", "environment_loss_db", "note"]
        import csv as _csv
        import io as _io
        # Quote properly: names and the explanatory note contain commas, and a
        # None renders as an empty cell rather than the literal text "None".
        buf = _io.StringIO()
        w = _csv.writer(buf, lineterminator="\n")
        w.writerow(header)
        for r in rows:
            w.writerow(["" if r.get(h) is None else r.get(h) for h in header])
        lines = [buf.getvalue().rstrip("\n")]
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


# ---- site inventory interchange (CSV) --------------------------------
# A cluster study is unusable at real scale if the only way in is clicking
# sites onto a map one at a time: an operator's estate arrives as a CSV export
# from their OSS, and an evaluation that starts with retyping 200 coordinates
# does not continue. Same column names in and out, so a round trip is lossless.
_SITE_CSV_COLUMNS = ("name", "lat", "lon", "antenna_azimuth_deg",
                     "downtilt_deg", *_SITE_RADIO_FIELDS,
                     "antenna_beamwidth_deg")


@router.post("/sites/parse-csv")
async def parse_sites_csv(file: UploadFile = File(...)) -> dict:
    """Parse a site-inventory CSV into the `sites` array a cluster study takes.

    Tolerant on input, strict about saying what it did: unknown columns are
    ignored, blank cells inherit, and every rejected row is reported with its
    line number and reason rather than being dropped in silence.
    """
    import csv as _csv
    import io as _io

    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(413, "Site CSV exceeds the 2 MB limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "Site CSV must be UTF-8 encoded")

    reader = _csv.DictReader(_io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(422, "Site CSV has no header row")
    header = {(h or "").strip().lower(): (h or "") for h in reader.fieldnames}
    if "lat" not in header or "lon" not in header:
        raise HTTPException(
            422, "Site CSV needs at least 'lat' and 'lon' columns; found: "
                 + ", ".join(reader.fieldnames))

    sites: list[dict] = []
    skipped: list[dict] = []
    for i, row in enumerate(reader, start=2):        # row 1 is the header
        def cell(col: str) -> str:
            return (row.get(header.get(col, ""), "") or "").strip()

        entry: dict = {}
        try:
            entry["lat"] = float(cell("lat"))
            entry["lon"] = float(cell("lon"))
        except ValueError:
            skipped.append({"line": i, "reason": "lat/lon is not a number"})
            continue
        if not (-90 <= entry["lat"] <= 90 and -180 <= entry["lon"] <= 180):
            skipped.append({"line": i, "reason": "lat/lon out of range"})
            continue
        if cell("name"):
            entry["name"] = cell("name")[:80]
        bad = False
        for col in ("antenna_azimuth_deg", "downtilt_deg",
                    "antenna_beamwidth_deg", *_SITE_RADIO_FIELDS):
            v = cell(col)
            if v:
                try:
                    entry[col] = float(v)
                except ValueError:
                    skipped.append({"line": i,
                                    "reason": f"{col} is not a number: {v!r}"})
                    bad = True
                    break
        if bad:
            continue
        try:
            sites.append(SiteIn(**entry).model_dump())
        except Exception as exc:      # pydantic validation, e.g. bad azimuth
            skipped.append({"line": i, "reason": str(exc).splitlines()[0][:120]})
        if len(sites) >= 24:
            skipped.append({"line": i,
                            "reason": "cluster studies accept at most 24 sites"})
            break

    return {"sites": sites, "count": len(sites), "skipped": skipped,
            "columns": list(_SITE_CSV_COLUMNS)}


@router.post("/sites/export-csv")
def export_sites_csv(sites: list[SiteIn]) -> Response:
    """The inverse of parse-csv, so an estate can round-trip through a
    spreadsheet without losing the per-site radio parameters."""
    import csv as _csv
    import io as _io

    buf = _io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    w.writerow(_SITE_CSV_COLUMNS)
    for s in sites:
        w.writerow(["" if getattr(s, c, None) is None else getattr(s, c)
                    for c in _SITE_CSV_COLUMNS])
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sites.csv"'})


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
                st = site_tech(tech, s)
                polar = engine.compute_polar(
                    s.lat, s.lon, st, radius_m=radius_m,
                    n_radials=req.n_radials, n_steps=req.n_steps,
                    antenna_azimuth_deg=s.antenna_azimuth_deg,
                    antenna_beamwidth_deg=(s.antenna_beamwidth_deg
                                           if s.antenna_beamwidth_deg is not None
                                           else req.antenna_beamwidth_deg),
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
                                 "radius_m": radius_m, "polar": polar,
                                 "resolved": site_echo(s, st)})
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
    # Persist the engine's own figures (see the single-site save above).
    results_store.save("coverage", result_id, png, {
        "bounds": bounds,
        "stats": {
            "served_area_fraction": served_frac,
            "max_rx_power_dbm": max((s["max_rx_power_dbm"] for s in site_stats),
                                    default=None),
            "sites": len(site_stats),
        },
        "owner_id": user["id"] if user else None})

    sinr_out = None
    if sinr is not None:
        sinr_id = _uuid.uuid4().hex[:12]
        results_store.save("coverage", sinr_id, sinr.pop("png"),
                           {"bounds": bounds,
                            "owner_id": user["id"] if user else None})
        sinr_out = {"png_url": f"/api/rf/coverage/{sinr_id}.png", **sinr}

    return {
        "coverage_id": result_id,
        "png_url": f"/api/rf/coverage/{result_id}.png",
        "bounds": bounds,
        "legend": [{"label": s["name"], "color": s["color"],
                    "margin_db": 0} for s in site_stats],
        "stats": {
            # Each site's stats carry the parameters it ACTUALLY ran on, so a
            # per-site override is auditable rather than indistinguishable
            # from one that was silently ignored.
            "sites": [{**st, "resolved": c.get("resolved")}
                      for st, c in zip(site_stats, computed)],
            "served_area_fraction": served_frac,
            "radius_m": radius_m,
            "tx_elevation_m": computed[0]["polar"]["tx_elev"],
            "max_rx_power_dbm": max(s["max_rx_power_dbm"] for s in site_stats),
        },
        "sinr": sinr_out,
        "technology": {**tech, "key": req.technology},
        "warnings": warnings,
    }
