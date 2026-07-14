# AntennaMaster — Terrain & Georeferencing Module

Online radio antenna coverage simulator terrain stack: fuses **global SRTM 30 m
base elevation** with **local high-resolution DXF relief** into a single,
seamless terrain model used by the RF physics (Fresnel zones, knife-edge
diffraction, k = 4/3 effective-earth curvature).

The DXF is a *local override*: the app works globally with SRTM alone, and a
georeferenced DXF patches high-res detail over the base within its footprint.

## Architecture

```
backend/  (Python / FastAPI)
  app/services/dem/      Terrarium RGB tile fetcher, Z/X/Y disk cache,
                         seamless cross-tile bilinear sampling, geodesic profiles
  app/services/dxf/      ezdxf parsing (POINT, LWPOLYLINE elevation, POLYLINE/
                         POLYFACE, 3DFACE, MESH, TEXT/MTEXT spot heights),
                         3 georeferencing modes, scipy gridding, hillshade overlay
  app/services/terrain/  Fusion engine: DXF patch + 3-cell feather blending,
                         50 m mean-elevation validation vs SRTM
  app/services/rf/       k=4/3 earth curvature, Fresnel radii, knife-edge loss
  app/api/               FastAPI routes
frontend/ (Next.js / React-Leaflet / Recharts)
  components/DxfWizard   Upload → layer select → georeferencing modal
  components/MapView     TX/RX placement, DXF footprint polygon, hillshade overlay
  components/ProfileChart Provenance-colored profile (blue=SRTM, orange=DXF)
```

### Terrain fusion pipeline

1. **SRTM base** — Mapzen/AWS *Terrarium* tiles (open data, no API key):
   `elevation = (R·256 + G + B/256) − 32768`. Tiles are cached on disk under
   `backend/data/dem_cache/{z}/{x}/{y}.png` and never re-downloaded.
2. **DXF patch** — selected layers are parsed into a scattered point cloud and
   interpolated to a regular grid with `scipy.interpolate.griddata` (linear,
   nearest-neighbour fallback at the convex-hull fringe).
3. **Feathered fusion** — inside the DXF bounding box the DXF wins; across a
   ~3-grid-cell band at the boundary the two surfaces are cross-faded so no
   artificial cliff creates a false diffraction edge.
4. **Validation** — mean DXF elevation is compared to mean SRTM elevation over
   the same footprint; a difference > 50 m raises a strict API warning
   (typical cause: feet-vs-meters mixup or a bad transform).
5. **RF context** — the k = 4/3 effective-earth bulge is applied to the fused
   profile *before* any Fresnel / line-of-sight evaluation.

### Georeferencing modes

| Mode | Input | Method |
|---|---|---|
| Known CRS | EPSG code / PROJ string | `pyproj` reprojection to EPSG:4326 |
| Control points | 2–3 (DXF X/Y ↔ Lat/Lon) pairs | least-squares 2D Helmert (scale+rotation+translation) in a local AEQD plane; per-point + RMS residuals returned in meters |
| Origin + rotation | origin Lat/Lon, bearing of the +Y axis, unit scale | analytic similarity transform |

## Running

Backend (Python ≥ 3.11):

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend (Node ≥ 18) — proxies `/api/*` to the backend
(`BACKEND_URL`, default `http://localhost:8000`):

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

Tests (offline — fake DEM world + synthetic survey DXF):

```bash
cd backend && python -m pytest tests/ -q
```

## API summary

| Endpoint | Purpose |
|---|---|
| `POST /api/dxf/upload` | store DXF, return `dxf_id` + per-layer inventory (entity types, point counts, Z range) |
| `GET /api/dxf/{id}/layers` | layer inventory for the layer-selection UI |
| `POST /api/dxf/{id}/georeference` | apply a georeferencing mode, build the grid, validate vs SRTM; returns transform + residuals, footprint polygon, overlay bounds, validation warning |
| `GET /api/dxf/{id}/overlay.png` | semi-transparent hillshade of the DXF terrain (RGBA; transparent outside footprint) |
| `GET /api/terrain/profile` | geodesic TX→RX fused profile with per-sample provenance (`srtm`/`blend`/`dxf`), curved elevations (k applied), LOS, first-Fresnel lower edge and link analysis |
| `GET /api/terrain/elevation` | fused single-point elevation |
