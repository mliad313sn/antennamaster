"""FastAPI application entry point.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Server-side logs for operators: broad route-level excepts log the full
# traceback here before returning a sanitized HTTP error to the client.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from .api.routes_dxf import router as dxf_router
from .api.routes_indoor import router as indoor_router
from .api.routes_rf import router as rf_router
from .api.routes_terrain import router as terrain_router

app = FastAPI(
    title="AntennaMaster Terrain & Georeferencing API",
    description=(
        "Fuses global SRTM 30 m elevation (Terrarium tiles) with local "
        "high-resolution DXF relief data into a seamless terrain model for "
        "RF coverage simulation (Fresnel / knife-edge, k=4/3 earth)."
    ),
    version="1.0.0",
)

# The Next.js dev server runs on another port; origins are configurable via
# AM_CORS_ORIGINS (comma-separated), defaulting to open for dev setups.
from .config import CORS_ORIGINS  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dxf_router)
app.include_router(terrain_router)
app.include_router(rf_router)
app.include_router(indoor_router)


@app.get("/api/health")
def health() -> dict:
    """Liveness only: the process is up."""
    return {"status": "ok"}


@app.get("/api/ready")
def ready():
    """Readiness: can this worker actually serve studies?  Verifies the data
    dir is writable and reports (without failing on) DEM cache state, so
    orchestrators can pull broken workers out of rotation."""
    import os

    from fastapi.responses import JSONResponse

    from .config import DATA_DIR, DEM_CACHE_DIR
    checks = {"data_dir_writable": os.access(DATA_DIR, os.W_OK)}
    checks["dem_cache_present"] = any(DEM_CACHE_DIR.glob("*/*/*.png"))
    ok = checks["data_dir_writable"]
    return JSONResponse(status_code=200 if ok else 503,
                        content={"status": "ready" if ok else "degraded",
                                 "checks": checks})
