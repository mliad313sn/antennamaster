"""Central configuration for the terrain & georeferencing backend."""
from pathlib import Path

# Root directory for all persistent data (DEM tile cache, uploaded DXFs).
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# On-disk DEM tile cache, keyed by Z/X/Y (see services/dem/tiles.py).
DEM_CACHE_DIR = DATA_DIR / "dem_cache"

# Uploaded DXF files and their derived terrain grids.
DXF_STORE_DIR = DATA_DIR / "dxf_store"

# Mapzen/AWS "Terrarium" RGB-encoded elevation tiles (open data, no key).
# elevation = (R * 256 + G + B / 256) - 32768  [meters]
TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

# Zoom 12 ~= 38 m/px at the equator, close to the native SRTM 30 m posting.
DEM_ZOOM = 12

# Number of DXF grid cells over which the DXF->SRTM transition is feathered.
FUSION_FEATHER_CELLS = 3.0

# |mean(DXF) - mean(SRTM)| threshold (meters) that triggers the strict
# unit-mismatch / bad-transform validation warning.
VALIDATION_MEAN_DIFF_M = 50.0

# Effective earth radius factor for standard atmospheric refraction.
EARTH_RADIUS_M = 6_371_000.0
K_FACTOR_DEFAULT = 4.0 / 3.0

for _d in (DEM_CACHE_DIR, DXF_STORE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
