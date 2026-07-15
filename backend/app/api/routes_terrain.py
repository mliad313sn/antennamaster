"""Elevation-profile and link-analysis endpoints over the fused terrain."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

import numpy as np

from ..services.rf.models import MODEL_INFO, deygout_loss_db, path_loss_db
from ..services.rf.physics import analyze_path, apply_earth_curvature
from ..services.rf.technologies import get_technology, link_budget
from ..services.terrain.fusion import TerrainFusionService
from .routes_auth import current_user

# Process-wide fusion service (shares the DEM tile cache across requests).
_fusion = TerrainFusionService()

# Optional surface-model (DSM) fusion service: same machinery pointed at a
# Terrarium DSM source (buildings/canopy included), created lazily when
# AM_DSM_URL is configured.  Tests may inject one directly.
_surface_fusion: TerrainFusionService | None = None


def get_fusion_service() -> TerrainFusionService:
    return _fusion


def get_surface_fusion_service() -> TerrainFusionService | None:
    global _surface_fusion
    if _surface_fusion is not None:
        return _surface_fusion
    from ..config import DSM_CACHE_DIR, DSM_URL
    if not DSM_URL:
        return None
    from ..services.dem.tiles import TerrariumTileStore
    _surface_fusion = TerrainFusionService(
        store=TerrariumTileStore(cache_dir=DSM_CACHE_DIR, url_template=DSM_URL))
    return _surface_fusion


def resolve_fusion(surface: bool) -> TerrainFusionService:
    """The fusion service for a request; 422 when a DSM is asked for but
    not configured, so the client gets an actionable message."""
    if not surface:
        return get_fusion_service()
    svc = get_surface_fusion_service()
    if svc is None:
        raise HTTPException(422, "No surface model configured: set AM_DSM_URL "
                                 "to a Terrarium-encoded DSM tile source to "
                                 "use surface=true.")
    return svc

router = APIRouter(prefix="/api/terrain", tags=["terrain"])


@router.get("/elevation")
def point_elevation(lat: float = Query(ge=-90, le=90),
                    lon: float = Query(ge=-180, le=180),
                    dxf_id: str | None = None,
                    user: dict | None = Depends(current_user)) -> dict:
    """Fused elevation at a single point (SRTM, or DXF where available)."""
    fusion = get_fusion_service()
    grid = georef = None
    if dxf_id:
        from .routes_dxf import resolve_dxf
        session = resolve_dxf(dxf_id, user)   # 404/403/402/409 as needed
        grid, georef = session.grid, session.georef
    elev, w = fusion.fused_elevations(np.array([lat]), np.array([lon]), grid, georef)
    return {"lat": lat, "lon": lon, "elevation_m": float(elev[0]),
            "source": "dxf" if w[0] >= 0.5 else ("blend" if w[0] > 0 else "srtm")}


@router.get("/profile")
def terrain_profile(
    lat1: float = Query(ge=-90, le=90), lon1: float = Query(ge=-180, le=180),
    lat2: float = Query(ge=-90, le=90), lon2: float = Query(ge=-180, le=180),
    samples: int = Query(256, ge=16, le=2048),
    dxf_id: str | None = None,
    tx_height_m: float = Query(20.0, ge=0),
    rx_height_m: float = Query(10.0, ge=0),
    # No default: with a technology preset the preset frequency wins unless
    # explicitly overridden; without one we fall back to 446 MHz (PMR).
    freq_mhz: float | None = Query(None, gt=0),
    k_factor: float = Query(4.0 / 3.0, gt=0.1, le=10),
    # Optional full radio study along the path (any preset: 2G..5G, PMR, ...).
    technology: str | None = Query(None),
    model: str | None = Query(None),
    environment: str | None = Query(None),
    tx_power_dbm: float | None = Query(None),
    tx_gain_dbi: float | None = Query(None),
    rx_gain_dbi: float | None = Query(None),
    losses_db: float | None = Query(None),
    rx_sensitivity_dbm: float | None = Query(None),
    # Environmental excess losses (foliage clutter / weather for PtP):
    foliage_depth_m: float = Query(0.0, ge=0, le=400),
    rain_rate_mm_h: float = Query(0.0, ge=0, le=150),
    # ITU-R P.2108 statistical man-made clutter at the RX end: percentage of
    # locations not exceeded (0 = off, 50 = median, 90 = planning margin).
    clutter_pct: float = Query(0.0, ge=0, le=99.9),
    # Sample the surface model (DSM: buildings/canopy) instead of the bare
    # terrain - requires AM_DSM_URL to be configured.
    surface: bool = Query(False),
    user: dict | None = Depends(current_user),
) -> dict:
    """TX->RX elevation profile over the fused terrain, plus RF link analysis.

    Per-sample `source` tells the frontend which segments came from SRTM vs
    the DXF patch (for provenance color-coding).  `terrain_curved_m` has the
    k-factor earth bulge applied and is what the LOS/Fresnel numbers use.
    """
    fusion = resolve_fusion(surface)

    grid = georef = None
    dxf_active = False
    if dxf_id:
        from .routes_dxf import resolve_dxf
        session = resolve_dxf(dxf_id, user)
        grid, georef = session.grid, session.georef
        dxf_active = True

    try:
        prof = fusion.profile(lat1, lon1, lat2, lon2, n_samples=samples,
                              grid=grid, georef=georef)
    except Exception as exc:  # DEM fetch failures surface as 502, not 500
        raise HTTPException(502, f"Elevation data unavailable: {exc}") from exc

    # Effective frequency: explicit param > technology preset > 446 MHz.
    tech_preview = None
    if technology is not None:
        try:
            tech_preview = get_technology(technology)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    eff_freq = freq_mhz if freq_mhz is not None else (
        tech_preview["freq_mhz"] if tech_preview else 446.0)

    rf = analyze_path(prof.distances_m, prof.elevations_m,
                      tx_height_m=tx_height_m, rx_height_m=rx_height_m,
                      freq_mhz=eff_freq, k=k_factor)

    # Dual-k refraction reliability (microwave practice: 100% F1 at k=4/3
    # AND 60% F1 at k=2/3 sub-refraction) - cheap, always reported.
    from ..services.rf.planning import refraction_reliability
    refraction = refraction_reliability(prof.distances_m, prof.elevations_m,
                                        tx_height_m, rx_height_m, eff_freq)

    # Optional technology study: model path loss + Deygout diffraction on the
    # curved profile -> per-sample RX power + link budget at the RX end.
    study = None
    rx_power_per_point: np.ndarray | None = None
    if technology is not None:
        tech = tech_preview  # already resolved above
        # NOTE: heights use explicit None checks - a legitimate 0 m height
        # must reach the model, not silently fall back to the preset.
        overrides = {"model": model, "environment": environment,
                     "tx_power_dbm": tx_power_dbm, "tx_gain_dbi": tx_gain_dbi,
                     "rx_gain_dbi": rx_gain_dbi, "losses_db": losses_db,
                     "rx_sensitivity_dbm": rx_sensitivity_dbm,
                     "freq_mhz": freq_mhz,
                     "h_bs_m": tx_height_m if tx_height_m is not None else None,
                     "h_ut_m": rx_height_m if rx_height_m is not None else None}
        for key, val in overrides.items():
            if val is not None:
                tech[key] = val
        if tech["model"] not in MODEL_INFO:
            raise HTTPException(422, f"Unknown propagation model: {tech['model']!r}")

        d = prof.distances_m
        curved = apply_earth_curvature(d, prof.elevations_m, k=k_factor)
        pl, warnings = path_loss_db(tech["model"], np.maximum(d, 1.0),
                                    tech["freq_mhz"], tech["h_bs_m"],
                                    tech["h_ut_m"], tech["environment"])
        # Deygout diffraction on each TX->sample sub-path (interior samples).
        diff = np.zeros_like(d)
        for i in range(2, len(d)):
            diff[i] = deygout_loss_db(d[: i + 1], curved[: i + 1],
                                      tech["h_bs_m"], tech["h_ut_m"],
                                      tech["freq_mhz"])
        # Environmental excess losses along the path (foliage at the RX end,
        # gases + rain scale with distance - the PtP microwave essentials).
        from ..services.rf.environment import (clutter_loss_db,
                                               foliage_loss_db,
                                               gaseous_attenuation_db_per_km,
                                               rain_loss_db)
        fol = foliage_loss_db(tech["freq_mhz"], foliage_depth_m)
        gas_per_km = gaseous_attenuation_db_per_km(tech["freq_mhz"])
        gas = gas_per_km * d / 1000.0
        rain_end = rain_loss_db(tech["freq_mhz"], float(d[-1]), rain_rate_mm_h)
        # Per-sample rain via the same effective-path formula.
        rain = np.array([rain_loss_db(tech["freq_mhz"], float(di), rain_rate_mm_h)
                         for di in d]) if rain_rate_mm_h > 0 else np.zeros_like(d)
        # ITU-R P.2108 statistical clutter (distance-dependent per sample).
        clu = clutter_loss_db(tech["freq_mhz"], d, clutter_pct) \
            if clutter_pct > 0 else np.zeros_like(d)
        if clutter_pct > 0 and tech["freq_mhz"] < 500.0:
            warnings.append(
                "P.2108 clutter is defined for 0.5-67 GHz; the 0.5 GHz curve "
                "was used (conservative below 500 MHz).")

        mimo = float(tech.get("mimo_gain_db", 0.0))
        rx_power_per_point = (tech["tx_power_dbm"] + tech["tx_gain_dbi"]
                              + tech["rx_gain_dbi"] + mimo - tech["losses_db"]
                              - pl - diff - fol - gas - rain - clu)
        budget = link_budget(tech, float(pl[-1]), float(diff[-1]),
                             extra_losses_db=fol + float(gas[-1]) + rain_end
                             + float(clu[-1]))
        study = {
            "technology": {**tech, "key": technology},
            "path_loss_db": round(float(pl[-1]), 1),
            "diffraction_loss_db": round(float(diff[-1]), 1),
            "foliage_loss_db": round(fol, 1),
            "gaseous_loss_db": round(float(gas[-1]), 2),
            "rain_loss_db": round(rain_end, 1),
            "clutter_loss_db": round(float(clu[-1]), 1),
            "mimo_gain_db": mimo,
            "sensitivity_dbm": round(budget["sensitivity_dbm"], 1),
            "rx_power_dbm": round(budget["rx_power_dbm"], 1),
            "margin_db": round(budget["margin_db"], 1),
            "served": budget["served"],
            "warnings": warnings,
        }

    return {
        "samples": samples,
        "dxf_id": dxf_id if dxf_active else None,
        "surface": surface,
        "distance_m": prof.distances_m[-1] - prof.distances_m[0],
        "points": [
            {
                "d": round(float(d), 1),
                "lat": float(la), "lon": float(lo),
                "elev": round(float(e), 2),
                "elev_curved": round(float(ec), 2),
                "los": round(float(l), 2),
                "fresnel_lower": round(float(fl), 2),
                "source": s,
                "dxf_weight": round(float(w), 3),
                **({"rx_power_dbm": round(float(rx_power_per_point[i]), 1)}
                   if rx_power_per_point is not None else {}),
            }
            for i, (d, la, lo, e, ec, l, fl, s, w) in enumerate(zip(
                prof.distances_m, prof.lats, prof.lons, prof.elevations_m,
                rf["terrain_curved_m"], rf["los_m"], rf["fresnel1_lower_m"],
                prof.source, prof.dxf_weight))
        ],
        "study": study,
        "rf": {
            "line_of_sight_clear": rf["line_of_sight_clear"],
            "fresnel_clearance_ratio": round(rf["fresnel_clearance_ratio"], 3),
            "knife_edge_loss_db": round(rf["knife_edge_loss_db"], 2),
            "worst_obstruction_index": rf["worst_obstruction_index"],
            "worst_obstruction_v": round(rf["worst_obstruction_v"], 3),
            "k_factor": rf["k_factor"],
            "freq_mhz": eff_freq,
            "tx_height_m": tx_height_m,
            "rx_height_m": rx_height_m,
            "refraction": refraction,
        },
    }


@router.get("/heightmap/{level}/{x}/{y}.bin")
def heightmap_tile(level: int, x: int, y: int, size: int = Query(65, ge=17, le=129),
                   dxf_id: str | None = None, surface: bool = Query(False),
                   user: dict | None = Depends(current_user)):
    """int16 heightmap tile for the CesiumJS 3D terrain provider, sampled from
    the fused SRTM+DXF model (no Cesium Ion required)."""
    from fastapi.responses import Response

    from ..services.terrain.heightmap import heightmap_int16
    if level < 0 or level > 16 or x < 0 or y < 0:
        raise HTTPException(422, "tile out of range")
    fusion = resolve_fusion(surface)
    grid = georef = None
    if dxf_id:
        from .routes_dxf import resolve_dxf
        session = resolve_dxf(dxf_id, user)
        grid, georef = session.grid, session.georef
    try:
        data = heightmap_int16(fusion, level, x, y, size=size,
                               grid=grid, georef=georef)
    except Exception as exc:
        raise HTTPException(502, f"Elevation data unavailable: {exc}") from exc
    return Response(content=data, media_type="application/octet-stream",
                   headers={"Cache-Control": "max-age=3600",
                            "X-Heightmap-Size": str(size)})


@router.get("/itm")
def itm_study(
    lat1: float = Query(ge=-90, le=90), lon1: float = Query(ge=-180, le=180),
    lat2: float = Query(ge=-90, le=90), lon2: float = Query(ge=-180, le=180),
    h_tx_m: float = Query(30.0, ge=0, le=500),
    h_rx_m: float = Query(10.0, ge=0, le=500),
    freq_mhz: float | None = Query(None, gt=0),
    technology: str | None = Query(None),
    reliability: float = Query(0.5, gt=0, lt=1),
    confidence: float = Query(0.5, gt=0, lt=1),
    samples: int = Query(256, ge=16, le=2048),
    dxf_id: str | None = None, surface: bool = Query(False),
    k_factor: float = Query(4.0 / 3.0, gt=0.1, le=10),
    user: dict | None = Depends(current_user),
) -> dict:
    """Longley-Rice-family Irregular Terrain Model over the fused profile: a
    median reference loss plus a reliability quantile (time/situation), the one
    statistical model the DEM reference tools have that empirical curves lack."""
    eff_freq = freq_mhz
    if technology is not None:
        try:
            eff_freq = freq_mhz or get_technology(technology)["freq_mhz"]
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    eff_freq = eff_freq or 446.0

    fusion = resolve_fusion(surface)
    grid = georef = None
    if dxf_id:
        from .routes_dxf import resolve_dxf
        session = resolve_dxf(dxf_id, user)
        grid, georef = session.grid, session.georef
    try:
        prof = fusion.profile(lat1, lon1, lat2, lon2, n_samples=samples,
                              grid=grid, georef=georef)
    except Exception as exc:
        raise HTTPException(502, f"Elevation data unavailable: {exc}") from exc

    from ..services.rf.itm import itm_point_to_point
    return {"freq_mhz": eff_freq,
            **itm_point_to_point(prof.distances_m, prof.elevations_m,
                                 h_tx_m, h_rx_m, eff_freq,
                                 reliability=reliability, confidence=confidence,
                                 k=k_factor)}


@router.get("/optimize-heights")
def optimize_heights(
    lat1: float = Query(ge=-90, le=90), lon1: float = Query(ge=-180, le=180),
    lat2: float = Query(ge=-90, le=90), lon2: float = Query(ge=-180, le=180),
    samples: int = Query(256, ge=16, le=2048),
    dxf_id: str | None = None,
    surface: bool = Query(False),
    tx_height_m: float = Query(20.0, ge=0),
    rx_height_m: float = Query(10.0, ge=0),
    freq_mhz: float | None = Query(None, gt=0),
    technology: str | None = Query(None),
    k_factor: float = Query(4.0 / 3.0, gt=0.1, le=10),
    max_height_m: float = Query(120.0, gt=1, le=500),
    user: dict | None = Depends(current_user),
) -> dict:
    """Minimum antenna heights that clear the path: for each end (holding
    the other at its current height), the smallest height achieving bare
    LOS and the 60% first-Fresnel clearance rule.  null = not achievable
    within ``max_height_m``."""
    fusion = resolve_fusion(surface)
    grid = georef = None
    if dxf_id:
        from .routes_dxf import resolve_dxf
        session = resolve_dxf(dxf_id, user)
        grid, georef = session.grid, session.georef

    if technology is not None:
        try:
            tech = get_technology(technology)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        eff_freq = freq_mhz if freq_mhz is not None else tech["freq_mhz"]
    else:
        eff_freq = freq_mhz if freq_mhz is not None else 446.0

    try:
        prof = fusion.profile(lat1, lon1, lat2, lon2, n_samples=samples,
                              grid=grid, georef=georef)
    except Exception as exc:
        raise HTTPException(502, f"Elevation data unavailable: {exc}") from exc

    from ..services.rf.planning import min_height_m
    d, e = prof.distances_m, prof.elevations_m
    out = {}
    for crit in ("los", "f1_60"):
        out[crit] = {
            "min_tx_height_m": min_height_m(
                d, e, eff_freq, rx_height_m, "tx", crit, k_factor, max_height_m),
            "min_rx_height_m": min_height_m(
                d, e, eff_freq, tx_height_m, "rx", crit, k_factor, max_height_m),
        }
    return {
        "freq_mhz": eff_freq, "k_factor": k_factor,
        "current": {"tx_height_m": tx_height_m, "rx_height_m": rx_height_m},
        "max_height_m": max_height_m,
        "criteria": out,
        "note": "each minimum holds the other end at its current height",
    }


@router.get("/profile.csv")
def terrain_profile_csv(
    lat1: float = Query(ge=-90, le=90), lon1: float = Query(ge=-180, le=180),
    lat2: float = Query(ge=-90, le=90), lon2: float = Query(ge=-180, le=180),
    samples: int = Query(256, ge=16, le=2048),
    dxf_id: str | None = None,
    tx_height_m: float = Query(20.0, ge=0),
    rx_height_m: float = Query(10.0, ge=0),
    freq_mhz: float | None = Query(None, gt=0),
    k_factor: float = Query(4.0 / 3.0, gt=0.1, le=10),
    technology: str | None = Query(None),
    model: str | None = Query(None),
    environment: str | None = Query(None),
    tx_power_dbm: float | None = Query(None),
    tx_gain_dbi: float | None = Query(None),
    rx_gain_dbi: float | None = Query(None),
    losses_db: float | None = Query(None),
    rx_sensitivity_dbm: float | None = Query(None),
    foliage_depth_m: float = Query(0.0, ge=0, le=400),
    rain_rate_mm_h: float = Query(0.0, ge=0, le=150),
    clutter_pct: float = Query(0.0, ge=0, le=99.9),
    surface: bool = Query(False),
    user: dict | None = Depends(current_user),
):
    """The elevation/link profile as CSV - the deliverable engineers attach
    to reports and load into Excel/GIS.  Same parameters as /profile."""
    from fastapi.responses import Response

    data = terrain_profile(
        lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2, samples=samples,
        dxf_id=dxf_id, tx_height_m=tx_height_m, rx_height_m=rx_height_m,
        freq_mhz=freq_mhz, k_factor=k_factor, technology=technology,
        model=model, environment=environment,
        tx_power_dbm=tx_power_dbm, tx_gain_dbi=tx_gain_dbi,
        rx_gain_dbi=rx_gain_dbi, losses_db=losses_db,
        rx_sensitivity_dbm=rx_sensitivity_dbm,
        foliage_depth_m=foliage_depth_m, rain_rate_mm_h=rain_rate_mm_h,
        clutter_pct=clutter_pct, surface=surface,
        user=user)

    has_rx = data["points"] and "rx_power_dbm" in data["points"][0]
    header = ["distance_m", "lat", "lon", "elevation_m", "elevation_curved_m",
              "los_m", "fresnel1_lower_m", "source", "dxf_weight"]
    if has_rx:
        header.append("rx_power_dbm")
    lines = [
        f"# AntennaMaster profile: TX {lat1},{lon1} h={tx_height_m}m -> "
        f"RX {lat2},{lon2} h={rx_height_m}m",
        f"# freq_mhz={data['rf']['freq_mhz']} k={k_factor:.3f} "
        f"technology={technology or '-'} dxf={dxf_id or '-'}",
        ",".join(header),
    ]
    for p in data["points"]:
        row = [p["d"], p["lat"], p["lon"], p["elev"], p["elev_curved"],
               p["los"], p["fresnel_lower"], p["source"], p["dxf_weight"]]
        if has_rx:
            row.append(p.get("rx_power_dbm", ""))
        lines.append(",".join(str(v) for v in row))
    return Response(
        content="\n".join(lines) + "\n", media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="profile.csv"'})


@router.get("/profile.kml")
def terrain_profile_kml(
    lat1: float = Query(ge=-90, le=90), lon1: float = Query(ge=-180, le=180),
    lat2: float = Query(ge=-90, le=90), lon2: float = Query(ge=-180, le=180),
    samples: int = Query(128, ge=16, le=1024),
    dxf_id: str | None = None,
    surface: bool = Query(False),
    tx_height_m: float = Query(20.0, ge=0),
    rx_height_m: float = Query(10.0, ge=0),
    freq_mhz: float = Query(446.0, gt=0),
    k_factor: float = Query(4.0 / 3.0, gt=0.1, le=10),
    kmz: bool = Query(False),
    user: dict | None = Depends(current_user),
):
    """Export the TX→RX link as KML/KMZ for Google Earth / GIS: TX & RX
    placemarks, the line-of-sight path (green=clear, red=obstructed) and the
    terrain profile beneath it.  ``kmz=true`` returns a zipped KMZ."""
    from fastapi.responses import Response
    fusion = resolve_fusion(surface)
    grid = georef = None
    if dxf_id:
        from .routes_dxf import resolve_dxf
        session = resolve_dxf(dxf_id, user)
        grid, georef = session.grid, session.georef
    try:
        prof = fusion.profile(lat1, lon1, lat2, lon2, n_samples=samples,
                              grid=grid, georef=georef)
    except Exception as exc:
        raise HTTPException(502, f"Elevation data unavailable: {exc}") from exc

    rf = analyze_path(prof.distances_m, prof.elevations_m,
                      tx_height_m=tx_height_m, rx_height_m=rx_height_m,
                      freq_mhz=freq_mhz, k=k_factor)
    terrain = [(float(lo), float(la), float(e))
               for la, lo, e in zip(prof.lats, prof.lons, prof.elevations_m)]

    from ..services.gis_kml import kmz_wrap, los_kml
    kml = los_kml(
        tx_lat=lat1, tx_lon=lon1, rx_lat=lat2, rx_lon=lon2,
        tx_ground_m=float(prof.elevations_m[0]),
        rx_ground_m=float(prof.elevations_m[-1]),
        tx_height_m=tx_height_m, rx_height_m=rx_height_m,
        terrain=terrain, los_clear=rf["line_of_sight_clear"],
        title="AntennaMaster line-of-sight")
    # The export is audit-logged centrally by AuditMiddleware (user + IP).
    if kmz:
        return Response(
            content=kmz_wrap(kml), media_type="application/vnd.google-earth.kmz",
            headers={"Content-Disposition": 'attachment; filename="link.kmz"'})
    return Response(
        content=kml, media_type="application/vnd.google-earth.kml+xml",
        headers={"Content-Disposition": 'attachment; filename="link.kml"'})
