"""Central configuration for the terrain & georeferencing backend.

Every value can be overridden with an ``AM_``-prefixed environment variable
(listed next to each setting) so self-hosting organizations can adapt the
DEM source, cache locations and limits without forking the code.
"""
import os
from pathlib import Path


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# Root directory for all persistent data (DEM tile cache, uploaded DXFs,
# simulation results).                                    [AM_DATA_DIR]
DATA_DIR = Path(os.environ.get(
    "AM_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))

# On-disk DEM tile cache, keyed by Z/X/Y (see services/dem/tiles.py).
DEM_CACHE_DIR = DATA_DIR / "dem_cache"

# Uploaded DXF files and their derived terrain grids.
DXF_STORE_DIR = DATA_DIR / "dxf_store"

# Simulation rasters (outdoor coverage / indoor heatmaps), disk-backed so
# any uvicorn worker can serve any result and restarts don't lose them.
RESULTS_DIR = DATA_DIR / "results"

# DEM tile source: any Terrarium-encoded XYZ endpoint works.
# elevation = (R * 256 + G + B / 256) - 32768  [meters]   [AM_DEM_URL]
TERRARIUM_URL = os.environ.get(
    "AM_DEM_URL",
    "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png")

# Zoom 12 ~= 38 m/px at the equator, close to the native SRTM 30 m posting.
#                                                          [AM_DEM_ZOOM]
DEM_ZOOM = _env_int("AM_DEM_ZOOM", 12)

# Optional Digital SURFACE Model source (Terrarium-encoded XYZ): elevations
# that include buildings/canopy.  When set, profile and coverage requests
# may pass surface=true to treat those as obstructions.    [AM_DSM_URL]
DSM_URL = os.environ.get("AM_DSM_URL") or None
DSM_CACHE_DIR = DATA_DIR / "dsm_cache"

# Number of DXF grid cells over which the DXF->SRTM transition is feathered.
#                                                          [AM_FEATHER_CELLS]
FUSION_FEATHER_CELLS = _env_float("AM_FEATHER_CELLS", 3.0)

# |mean(DXF) - mean(SRTM)| threshold (meters) that triggers the strict
# unit-mismatch / bad-transform validation warning.        [AM_VALIDATION_DIFF_M]
VALIDATION_MEAN_DIFF_M = _env_float("AM_VALIDATION_DIFF_M", 50.0)

# Effective earth radius factor for standard atmospheric refraction.
EARTH_RADIUS_M = 6_371_000.0
K_FACTOR_DEFAULT = 4.0 / 3.0

# Upload cap for DXF files, bytes.                         [AM_MAX_DXF_MB]
MAX_DXF_BYTES = _env_int("AM_MAX_DXF_MB", 100) * 1024 * 1024

# On-disk DEM tile cache budget, MB (oldest tiles evicted beyond this).
#                                                          [AM_DEM_CACHE_MB]
DEM_CACHE_BUDGET_MB = _env_int("AM_DEM_CACHE_MB", 2048)

# Comma-separated CORS origins; '*' (default) for open dev setups.
#                                                          [AM_CORS_ORIGINS]
CORS_ORIGINS = [o.strip() for o in os.environ.get("AM_CORS_ORIGINS", "*").split(",")]

for _d in (DEM_CACHE_DIR, DXF_STORE_DIR, RESULTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
