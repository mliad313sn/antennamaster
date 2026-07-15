# AntennaMaster — RF Coverage Simulator

Online radio coverage simulator for **any radio study — GSM/2G, UMTS/3G,
LTE/4G, 5G NR (down to mmWave), PMR/TETRA, FM/DVB-T broadcast, Wi-Fi,
LoRaWAN IoT and microwave PtP** — built on a terrain stack that fuses
**global SRTM 30 m base elevation** with **local high-resolution DXF relief**
into a single, seamless model used by the RF physics (Fresnel zones,
Deygout multi-knife-edge diffraction, k = 4/3 effective-earth curvature).

The DXF is a *local override*: the app works globally with SRTM alone, and a
georeferenced DXF patches high-res detail over the base within its footprint.

**Start with `docs/USER_GUIDE.md`** — the complete user guide covering every
setting and capability. See `docs/ASSESSMENT.md` for the low-level audit and
the feature benchmark against SPLAT!, Radio Mobile, CloudRF and commercial
suites.

## Radio studies

* **Propagation models**: free space (ITU-R P.525), Okumura-Hata,
  COST-231 Hata, 3GPP TR 38.901 RMa/UMa/UMi (LOS/NLOS, valid to 100 GHz) —
  all floor-bounded by FSPL, with validity-range warnings. Terrain-aware
  **Deygout** diffraction (k=4/3 curved fused profile) is added on top.
* **Technology presets** (all overridable): GSM 900/1800 · UMTS 900/2100 ·
  LTE 800/1800/2600 · 5G NR n28/n78/n257 (28 GHz mmWave) · TETRA · PMR446 ·
  FM · DVB-T · Wi-Fi 2.4/5.8 · LoRaWAN 868 · 18 GHz PtP · **Private LTE
  B48/CBRS · Private 5G NR n77 · NB-IoT/LTE-M · VHF land mobile 150 MHz**
  · custom — 23 presets, operator-extensible via `technologies.json`.
* **Point-to-point link budget**: per-sample RX power along the profile,
  path loss + diffraction split, margin vs receiver sensitivity.
* **Area coverage**: polar-sweep simulation from the TX (omni or 3GPP
  parametric sector antenna), margin-classed raster overlay with legend and
  served-area statistics.
* **Environmental & clutter losses**: Weissberger foliage, ITU-R P.838/P.530
  rain, P.676 gases and **ITU-R P.2108 statistical clutter** (the man-made
  land-use loss elevation data cannot see) stack on any model.
* **Multi-site & interference**: best-server composites over up to 8 sites
  plus a **co-channel SINR map** (S/(I+N), worst-case reuse-1) with mean
  SINR, ≥6 dB area and cell-edge statistics.
* **Surface models**: point `AM_DSM_URL` at a Terrarium-encoded DSM and any
  profile/coverage can treat buildings and canopy as obstructions
  (`surface=true`).
* **Map providers**: OSM, OpenTopoMap, Carto Light/Dark, Esri Imagery/Topo
  out of the box, plus any custom XYZ tile template.

## Indoor & underground studies

Studies no DEM-based tool can run, using a DXF as *structure* instead of relief:

* **Floor plan / metro / mine coverage** — upload a DXF plan, assign a wall
  material per layer (12-material library, dB per crossing, frequency
  interpolated), click the plan to place the TX, and get a COST-231
  multi-wall heatmap in drawing coordinates — no georeferencing needed.
  **Multi-floor**: a COST-231 floor-penetration term (non-linear saturation)
  covers TX placements N storeys from the mapped floor.
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
  app/services/rf/       k=4/3 curvature, Fresnel, Deygout, environmental
                         losses (foliage/rain/gases), MSI antenna patterns
  app/services/indoor/   floor-plan multi-wall engine, material library
  app/services/saas/     accounts, tiers, projects, jobs, PDF reports, costs
  app/api/               FastAPI routes
frontend/ (Next.js / React-Leaflet / Recharts)
  components/DxfWizard   Upload → layer select → georeferencing modal
  components/MapView     TX/RX placement, DXF footprint polygon, hillshade overlay
  components/ProfileChart Provenance-colored profile (blue=SRTM, orange=DXF)
  components/SimpleMode  Non-technical outcome picker → preset mapping
  components/Tour        First-run guided walkthrough (react-joyride)
  locales/{en,fr}        Bilingual UI strings (react-i18next), PWA offline
```

The UI is **bilingual (EN/FR)**, has a **Simple Mode** that hides the RF
parameters behind plain-language deployment scenarios, a **guided tour** for
first-time users, and **offline (PWA)** field caching.

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

## SaaS & workspaces (optional layer)

Accounts, role dashboards (Command Center / Tactical / Pitch), saved &
shareable projects, tier entitlements, CAPEX/OPEX estimates, branded PDF
reports, async jobs with progress. Self-hosted installs keep every feature
free by default; `AM_SAAS_MODE=1` activates tier gating. Endpoints under
`/api/auth`, `/api/projects`, `/api/saas` — full schema and tier matrix in
`SaaS_ARCHITECTURE.md`.

## Deployment

Three supported ways to run it — full instructions in
[`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md):

```bash
docker compose up -d --build   # Docker (servers, air-gapped sites)
./install.sh && ./launch_simulator.sh   # local install (Linux/macOS; .bat on Windows)
```

- **Docker** — multi-stage images, private network, persistent `am_data`
  volume (embedded SQLite, no separate DB); `deploy/package_offline.sh`
  exports a `.tar` for air-gapped sites.
- **Local installer** — `install.sh`/`install.bat` (prereq checks → venv →
  deps → build); `launch_simulator.*` boots both servers, waits for health
  and opens the browser.
- **systemd** — `deploy/rf-simulator.service` for a persistent Linux service.

## Running (development)

One command (backend :8000 + frontend :3000):

```bash
./start.sh              # or: ./start.sh --check  (full test+benchmark gate)
```

Manual setup:

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
| `POST /api/rf/antenna` | upload an MSI Planet measured antenna pattern (dBd→dBi, tilt, H/V cuts) |
| `GET /api/rf/antennas` | uploaded patterns with gains and -3 dB beamwidths |
| `POST /api/rf/coverage/multi` | best-server composite over up to 8 sites (per-site colors + shares) |
| `GET /api/rf/technologies` | all radio-study presets (2G→5G, PMR, broadcast, WLAN, IoT, PtP) |
| `GET /api/rf/portable-profiles` | LMR portable/mobile radio profiles (body loss, 1.5 m height, building/vehicle penetration, EIRP) + DAQ ladder |
| `POST /api/rf/talkback` | **two-way LMR link**: talk-out (base→portable) + talk-in (portable→base) over one reciprocal path, TIA-4046 DAQ per direction + combined (min) |
| `POST /api/rf/talkback/batch` | grade ≤200 portable locations for two-way talk-back against one base/repeater |
| `POST /api/rf/repeater/design` | repeater donor/coverage antenna isolation, feedback-stable max gain, cascade spacing for continuous talk-back |
| `GET /api/rf/scenarios` | plain-language Simple-Mode scenarios → preset mapping |
| `GET /api/rf/equipment` | hardware catalog (Wi-Fi/Private LTE/PTP/PMR) for the Equipment Selector |
| `GET /api/terrain/profile.kml` | line-of-sight KML/KMZ (TX/RX + LoS + terrain) for Google Earth/GIS |
| `GET /api/basemap/{z}/{x}/{y}.png` | local OSM base-map tile server (offline fallback) |
| `GET /api/rf/models` | propagation models with validity ranges |
| `POST /api/rf/coverage` | area coverage simulation from a TX site (radius, sector antenna, resolution, DXF fusion); returns raster URL + legend + stats |
| `GET /api/rf/coverage/{id}.png` | coverage raster overlay (RGBA, transparent where unserved) |
| `GET /api/rf/coverage/{id}.tif` | georeferenced GeoTIFF (EPSG:4326) for QGIS/ArcGIS/Atoll |
| `POST /api/rf/batch` | qualify ≤200 receiver locations against one TX (JSON or CSV) |
| `POST /api/rf/site-search` | rank an n×n grid of candidate TX sites by served fraction |
| `GET /api/terrain/optimize-heights` | minimum TX/RX heights for LOS and 60% Fresnel |
| `POST /api/rf/emf-compliance` | **FCC OET-65 / ICNIRP RF-exposure** MPE limits + occupational/public exclusion-zone distances |
| `POST /api/rf/itm-profile` | **Longley-Rice / ITM** irregular-terrain loss over the fused profile, compared side-by-side with Deygout |
| `POST /api/rf/calibrate` | fit an empirical model correction (offset + distance slope) from measured RSSI; RMSE/MAE before/after |
| `POST /api/rf/calibrate/upload` | same, from an uploaded drive-test **CSV or GPX** walk-test file |
| `GET /api/saas/bom.csv` | fleet-scaled hardware bill of materials (CSV) |
| `GET /api/indoor/materials` | wall material attenuation library |
| `GET /api/indoor/presets` | tunnel wall permittivity + earth conductivity presets |
| `GET /api/indoor/{dxf_id}/preview.png` | floor-plan linework preview (bounds in `X-Plan-Bounds` header) |
| `POST /api/indoor/coverage` | COST-231 multi-wall heatmap over a DXF floor plan |
| `POST /api/indoor/ap-solve` | **automated AP placement**: solves min AP count + [x,y,z] positions for a coverage/capacity target, roaming (−67 dBm) overlap check, non-overlapping channel plan (graph colouring) |
| `GET /api/indoor/tunnel` | tunnel/mine waveguide link profile (Emslie model) |
| `GET /api/indoor/leaky-cables` | radiating-cable presets (loss dB/100 m, coupling loss) |
| `POST /api/indoor/leaky-feeder` | **radiating-cable (leaky feeder) design**: RX vs distance, auto inline-amplifier spacing, moving-train continuous-service KPI; cable length direct or measured from a DXF polyline layer |
| `GET /api/indoor/tte` | through-the-earth VLF link budget |
| `GET /api/ai/status` | Copilot config (configured?, model, tool count) — no secrets |
| `GET /api/ai/tools` | MCP-format manifest of simulation tools the Copilot can call |
| `POST /api/ai/tools/{name}` | invoke a simulation tool by name (offline, deterministic) |
| `POST /api/ai/chat` | **Design Copilot** — agentic tool-use over the engines, plain-language answer + tool trace (needs `AM_ANTHROPIC_API_KEY`) |
| `POST /api/ai/vision/floorplan` | vision: propose wall materials + candidate AP/mast locations from a floor-plan image |
