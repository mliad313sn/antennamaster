# AntennaMaster — RF Coverage Simulator

Online radio coverage simulator for **any radio study — GSM/2G, UMTS/3G,
LTE/4G, 5G NR (down to mmWave), PMR/TETRA, FM/DVB-T broadcast, Wi-Fi,
LoRaWAN IoT and microwave PtP** — built on a terrain stack that fuses
**global SRTM 30 m base elevation** with **local high-resolution DXF relief**
into a single, seamless model used by the RF physics (Fresnel zones,
Deygout multi-knife-edge diffraction, k = 4/3 effective-earth curvature).

The DXF is a *local override*: the app works globally with SRTM alone, and a
georeferenced DXF patches high-res detail over the base within its footprint.

See `docs/ASSESSMENT.md` for the low-level audit and the feature benchmark
against SPLAT!, Radio Mobile, CloudRF and commercial suites.

## Radio studies

* **Propagation models**: free space (ITU-R P.525), Okumura-Hata,
  COST-231 Hata, 3GPP TR 38.901 RMa/UMa/UMi (LOS/NLOS, valid to 100 GHz) —
  all floor-bounded by FSPL, with validity-range warnings. Terrain-aware
  **Deygout** diffraction (k=4/3 curved fused profile) is added on top.
* **Technology presets** (all overridable): GSM 900/1800 · UMTS 900/2100 ·
  LTE 800/1800/2600 · 5G NR n28/n78/n257 (28 GHz mmWave) · TETRA · PMR446 ·
  FM · DVB-T · Wi-Fi 2.4/5.8 · LoRaWAN 868 · 18 GHz PtP · custom.
* **Point-to-point link budget**: per-sample RX power along the profile,
  path loss + diffraction split, margin vs receiver sensitivity.
* **Area coverage**: polar-sweep simulation from the TX (omni or 3GPP
  parametric sector antenna), margin-classed raster overlay with legend and
  served-area statistics.
* **Map providers**: OSM, OpenTopoMap, Carto Light/Dark, Esri Imagery/Topo
  out of the box, plus any custom XYZ tile template.

## Indoor & underground studies

Studies no DEM-based tool can run, using a DXF as *structure* instead of relief:

* **Floor plan / metro / mine coverage** — upload a DXF plan, assign a wall
  material per layer (12-material library, dB per crossing, frequency
  interpolated), click the plan to place the TX, and get a COST-231
  multi-wall heatmap in drawing coordinates — no georeferencing needed.
* **Tunnel & mine gallery links** — Emslie waveguide model (dominant-mode
  dB/m from cross-section, wall permittivity, roughness, tilt) combined with
  the direct ray; reproduces why UHF outranges VHF underground.
* **Through-the-earth (TTE)** — VLF magnetic-loop links through conductive
  ground: skin-depth attenuation + near-field 1/r³ spreading, with ground
  conductivity presets. ITU-R P.1238 is also available for site-general
  indoor estimates.

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
| `GET /api/terrain/profile` | geodesic TX→RX fused profile with per-sample provenance (`srtm`/`blend`/`dxf`), curved elevations (k applied), LOS, first-Fresnel lower edge and link analysis; add `technology=` for a full link-budget study (per-sample RX power, Deygout loss, margin) |
| `GET /api/terrain/elevation` | fused single-point elevation |
| `GET /api/rf/technologies` | all radio-study presets (2G→5G, PMR, broadcast, WLAN, IoT, PtP) |
| `GET /api/rf/models` | propagation models with validity ranges |
| `POST /api/rf/coverage` | area coverage simulation from a TX site (radius, sector antenna, resolution, DXF fusion); returns raster URL + legend + stats |
| `GET /api/rf/coverage/{id}.png` | coverage raster overlay (RGBA, transparent where unserved) |
| `GET /api/indoor/materials` | wall material attenuation library |
| `GET /api/indoor/presets` | tunnel wall permittivity + earth conductivity presets |
| `GET /api/indoor/{dxf_id}/preview.png` | floor-plan linework preview (bounds in `X-Plan-Bounds` header) |
| `POST /api/indoor/coverage` | COST-231 multi-wall heatmap over a DXF floor plan |
| `GET /api/indoor/tunnel` | tunnel/mine waveguide link profile (Emslie model) |
| `GET /api/indoor/tte` | through-the-earth VLF link budget |
