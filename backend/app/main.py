"""FastAPI application entry point.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes_dxf import router as dxf_router
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

# The Next.js dev server runs on another port; allow it (and any origin in
# dev - tighten via a reverse proxy in production).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dxf_router)
app.include_router(terrain_router)
app.include_router(rf_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
