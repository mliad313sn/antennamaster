# AntennaMaster — Complete User Guide

Everything you can do with AntennaMaster, every setting it exposes, and what
each one means. All numbers in this guide are taken directly from the code.

Companion documents:
- `README.md` — quick overview and architecture
- `INSTALL_GUIDE.md` — cross-platform install & launch (Windows/macOS/Linux)
- `docs/CAPABILITIES.md` — condensed capability/capacity matrix
- `docs/ROADMAP.md` — five-layer capability model & delivered phases
- `VISION_ARCHITECTURE.md` — 3D digital twin, live telemetry, drone LiDAR
- `SaaS_ARCHITECTURE.md` — multi-tenant/SaaS internals
- `http://localhost:8010/docs` — live interactive OpenAPI reference

---

## Table of contents

1. [Getting started](#1-getting-started)
2. [The planner (main screen)](#2-the-planner-main-screen)
3. [DXF terrain workflow](#3-dxf-terrain-workflow)
4. [Point-to-point radio studies](#4-point-to-point-radio-studies)
5. [Area coverage simulation](#5-area-coverage-simulation)
6. [Multi-site best-server maps](#6-multi-site-best-server-maps)
7. [Antenna patterns](#7-antenna-patterns)
8. [Indoor & underground studio](#8-indoor--underground-studio)
9. [Reading the profile chart](#9-reading-the-profile-chart)
10. [Accounts, roles & dashboards](#10-accounts-roles--dashboards)
11. [Projects, sharing & reports](#11-projects-sharing--reports)
12. [Subscription tiers](#12-subscription-tiers)
13. [Reference: technology presets](#13-reference-technology-presets)
14. [Reference: propagation models](#14-reference-propagation-models)
15. [Reference: materials & presets](#15-reference-materials--presets)
16. [Reference: every setting](#16-reference-every-setting)
17. [Server configuration (environment variables)](#17-server-configuration-environment-variables)
18. [Limits & capacities](#18-limits--capacities)
19. [Troubleshooting](#19-troubleshooting)
20. [Advanced modules, 3D digital twin & live operations](#20-advanced-modules-3d-digital-twin--live-operations)

---

## 1. Getting started

### One-command start

```bash
./install.sh          # macOS/Linux: scan the host, install missing runtimes, build
./launch.sh           # boot both servers, wait for health, open the browser
```

On Windows use `install.ps1` / `launch.ps1` (PowerShell). The installer
auto-resolves Python 3.10+, Node 18+ and any build tools; see `INSTALL_GUIDE.md`
for the full matrix. For development you can still use:

```bash
./start.sh            # installs deps if needed, starts backend :8000 + frontend :3000
./start.sh --check    # runs the full QA gate first (backend tests, benchmarks, frontend tests)
```

### Manual start

Backend (Python ≥ 3.11):

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Frontend (Node ≥ 18; proxies `/api/*` to the backend via `BACKEND_URL`,
default `http://localhost:8010`):

```bash
cd frontend
npm install
npm run build && npm start     # or: npm run dev
```

Open **http://localhost:3010**. The REST API is self-documenting at
**http://localhost:8010/docs**.

### Health probes

- `GET /api/health` — liveness.
- `GET /api/ready` — readiness (data directory writable, DEM cache state).

### First study in 30 seconds

1. Click the map once to place the **TX** (transmitter), click again for **RX**.
2. The terrain profile, line-of-sight verdict and Fresnel clearance appear
   automatically — no DXF or account needed anywhere on Earth (SRTM 30 m).
3. Pick a technology preset (e.g. *LTE 800*) in the **Radio study** panel to
   turn the profile into a full link budget with received power per sample.

---

## 2. The planner (main screen)

### Language, Simple Mode & the guided tour

- **Language** — the header has an **EN / FR** switcher. English and French
  ship out of the box; your choice is remembered. (Adding a language is just
  another `locales/<code>/common.json` file.)
- **Simple ↔ Expert** — the header toggle. **Simple Mode** hides the RF
  numbers (dBi, MHz, propagation model) and instead asks *"what are you
  trying to connect?"* — pick an outcome (connect two buildings, Wi-Fi for a
  vehicle fleet, handheld radios across a site, private 4G/5G, IoT sensors,
  mobile coverage, long-distance backhaul) and the right technology and
  settings are applied for you. **Expert** exposes every control.
- **Guided tour** — first-time visitors get a short walkthrough
  (placing points → choosing a technology → uploading a DXF → reading the
  heatmap). Replay it any time with the **❓** button.
- **Glossary tooltips** — every technical field has an **ⓘ** icon. Hover,
  focus or tap it for a plain-language, equation-free explanation (also
  translated).
- **Read the signal at any point** — once a coverage layer is on the map, click
  anywhere on it to read the predicted level there: received power (dBm), the
  fade margin, the quality grade, and the distance/bearing from the site. The
  value is read out of the same field that painted the raster, so the number
  can never disagree with the colour under your cursor.
- **Arrange panels (drag-and-drop layout)** — click **⠿ Arrange panels** at
  the top of the sidebar to reshape it into your own workspace. Grab a panel's
  **⠿** handle and drag it anywhere in the stack (or focus the handle and press
  **↑ / ↓** — no mouse needed), and click a panel's **👁 eye** to hide the tools
  you never use. Click **Done** to return to work; hidden panels disappear and a
  small badge on the button shows how many are tucked away. Your order and
  hidden set are saved in this browser and restored on every visit — **Reset**
  puts everything back to the default layout.

### Map & providers

| Setting | What it does |
|---|---|
| Base layer picker | 6 built-in providers: OpenStreetMap, OpenTopoMap, Carto Light, Carto Dark, Esri World Imagery, Esri World Topo |
| Custom XYZ URL | Any `{z}/{x}/{y}` tile template (private tile servers, orthophotos…) |
| Theme toggle | auto (follows OS) → dark → light; persisted |
| Language | English / French; persisted |

The map view (center/zoom) and the whole session (endpoints, study settings,
DXF reference) persist in `localStorage` and are restored on reload.

### Placing TX and RX

- **Click** the map: first click sets TX, second sets RX; further clicks move RX.
- **Type exact coordinates**: the TX/RX lat/lon fields accept free typing
  (values apply when they parse; you can clear the box while editing).
- **GPS**: *Use my location* sets the TX from the browser's geolocation (with
  a visible error if permission is denied).
- **Swap**: exchanges TX and RX in one click.
- **Search**: enter `lat, lon` directly or a place name (geocoded through
  OpenStreetMap Nominatim — needs internet).

### Antenna heights

`TX height` and `RX height` are meters **above ground level** at each end.
Leave a technology preset selected and heights are pre-filled with realistic
values (e.g. 30 m mast / 1.5 m handheld for GSM).

### Profile settings

| Setting | Range | Default | Meaning |
|---|---|---|---|
| Samples | 16–2,048 | 256 | points along the geodesic path |
| k-factor | 0.1–10 | 1.333 | effective-earth radius factor; 4/3 = standard atmosphere, 0.7 ≈ sub-refraction worst case, 2+ ≈ ducting |
| Foliage depth | 0–400 m | 0 | vegetation crossed by the path (Weissberger model) |
| Rain rate | 0–150 mm/h | 0 | rain fade (ITU-R P.838/P.530), matters above ~7 GHz |
| Clutter %loc | 0–99.9 | 0 (off) | ITU-R P.2108 statistical man-made clutter; 50 = median urban, 90 = conservative |
| Surface model | on/off | off | sample a DSM (buildings as obstructions); visible only when `AM_DSM_URL` is configured |

The profile recomputes automatically (debounced ~350 ms) whenever an input
changes. **Export CSV** downloads the full per-sample table with the same
study parameters applied.

---

## 3. DXF terrain workflow

A DXF is a *local override*: AntennaMaster works globally on SRTM alone, and a
georeferenced DXF patches higher-resolution relief inside its footprint.

### Step 1 — Upload

Drag-and-drop (or browse) a `.dxf` file into the wizard. Cap: **100 MB**
(`AM_MAX_DXF_MB`). Damaged files go through ezdxf's recovery loader.

The upload response includes **auto-detected hints**: coordinate magnitudes
are analyzed to suggest a probable UTM zone or a feet-based drawing, and the
wizard pre-fills the georeferencing mode accordingly.

### Step 2 — Pick terrain layers

Every layer is listed with its entity types, point count and Z-range, plus a
"terrain-likeness" heuristic that pre-selects plausible relief layers.
Elevation is extracted from:

- `POINT` entities (survey points)
- `LWPOLYLINE` with an `elevation` attribute (contour lines)
- `POLYLINE` — 2D/3D polylines, polyface meshes, polygon meshes
- `3DFACE` and `MESH`
- `TEXT`/`MTEXT` spot heights (regex-parsed, `EL=`/`H=` prefixes supported)

Duplicate XY points are de-duplicated; the scattered cloud is gridded with
`scipy.griddata` (linear, nearest-neighbour fallback at the hull fringe) to a
density-aware grid of at most 400×400 cells.

### Step 3 — Georeference (three modes)

| Mode | You provide | Best when |
|---|---|---|
| **Known CRS** | EPSG code or PROJ string (e.g. `EPSG:32633`) | the drawing is in a documented projected CRS (UTM, Lambert, state plane) |
| **Control points** | 2–3 pairs of DXF X/Y ↔ real Lat/Lon | you can identify surveyed corners/landmarks in the drawing |
| **Origin + bearing** | anchor Lat/Lon, true bearing of the +Y axis, unit (m/ft/yd/cm), optional origin offset | you know where the drawing origin sits and how it is rotated |

Control points solve a least-squares 2D **Helmert** transform (scale +
rotation + translation) in a local plane and report **per-point and RMS
residuals in meters** — if a residual is large, that control point is wrong.
An independent `z_scale` converts vertical units (e.g. `0.3048` for
elevations in feet).

### Validation & fusion

After georeferencing, the mean DXF elevation is cross-checked against mean
SRTM elevation over the same footprint. A difference above **50 m**
(`AM_VALIDATION_DIFF_M`) raises a strict warning — the classic causes are a
feet/meters mix-up or a wrong CRS.

In profiles and coverage, the DXF wins inside its bounding box; across a
**3-grid-cell feathered band** (`AM_FEATHER_CELLS`) the DXF and SRTM surfaces
are cross-faded so the seam never creates a false diffraction edge. Every
profile sample carries its provenance (`srtm` / `blend` / `dxf`), which the
chart colors blue/orange.

The map shows the DXF **footprint polygon** and a semi-transparent
**hillshade overlay** (hypsometric tint × analytic hillshade) so you can see
exactly what terrain the DXF contributes. DXF state is persisted server-side
and rebuilt automatically after a restart.

---

## 4. Point-to-point radio studies

Select a **technology preset** in the Radio study panel (see
[§13](#13-reference-technology-presets) for all 23). Every preset field can
be overridden.

### Study settings

| Setting | Meaning |
|---|---|
| Technology | preset bundle: frequency, powers, gains, sensitivity, heights, best-fit model |
| Model | override the propagation model ([§14](#14-reference-propagation-models)) |
| Environment | model-specific: urban/suburban/open (Hata), +metropolitan (COST-231), los/nlos (3GPP) |
| Frequency | MHz; out-of-validity values are clamped with an explicit API warning |
| TX power / TX gain / RX gain / losses | link-budget terms (dBm / dBi / dBi / dB) |
| RX sensitivity | threshold for the margin verdict (dBm) |
| Fade margin | extra dB subtracted before the verdict — plan ~5.5 dB for 90 % area confidence, ~8 dB for 95 % |
| Foliage depth | Weissberger vegetation loss (0–400 m) |
| Rain rate | ITU-R P.838/P.530 rain fade (0–150 mm/h) |
| Clutter %loc | ITU-R P.2108 statistical man-made clutter: 0 = off, 50 = median urban, 90 = conservative planning (0.5–67 GHz; distance-dependent) |
| Surface model | sample a DSM (buildings/canopy as obstructions) instead of bare terrain — shown when the server has `AM_DSM_URL` configured |
| k-factor | earth curvature (0.1–10, default 4/3) |

### What you get

- Per-sample **received power** along the path, path-loss / diffraction split.
- **LOS verdict** and **first Fresnel zone** clearance (60 % rule).
- **Worst obstruction**: location, height and knife-edge ν of the dominant
  obstacle, marked on the chart.
- **Margin vs sensitivity** verdict for the chosen technology.
- Terrain diffraction is always computed with **Deygout multi-knife-edge**
  (up to 3 edges, ITU-R P.526) on the k-curved *fused* profile — on top of
  whichever empirical model is active.

Channel-aware presets (Private LTE/5G/IoT) derive sensitivity from thermal
noise: `−174 + 10·log₁₀(BW) + NF + SINR`, and add MIMO gain to the budget.
With clutter enabled the study shows a separate **Clutter (P.2108)** line in
the loss breakdown (as do foliage, rain and gases).

### Refraction reliability (microwave)

Every profile response also carries a **dual-k reliability check** under
`rf.refraction` — the standard microwave test that a dependable hop clears
**100 % of the first Fresnel zone at k = 4/3** (standard atmosphere) **and
60 % at k = 2/3** (sub-refraction worst case). Fields: `f1_ratio_k43`,
`f1_ratio_k23`, and a boolean `reliable`. A hop that passes at 4/3 but fails
at 2/3 will drop out during anomalous propagation.

### Antenna height optimizer

`GET /api/terrain/optimize-heights` returns the **minimum TX and RX height**
(by bisection, holding the other end fixed) that achieves bare line of sight
and the 60 %-first-Fresnel rule — the "how tall does the mast need to be?"
question, answered without trial and error. `null` means the criterion is
unreachable within the height cap (default 120 m).

---

## 4a. Batch receiver qualification

For fixed-wireless / WISP work — qualifying many subscriber addresses against
one tower — the **Batch receivers** panel (and `POST /api/rf/batch`) takes a
list of up to 200 locations (`name,lat,lon` per line) and returns each one's
distance, RX power, margin, served verdict, LOS and Fresnel clearance in a
single call. The panel renders a sortable table, colours served/unserved,
lets you click a row to drop the RX pin there, and exports the whole set as
**CSV** (`?format=csv`) for a CRM or spreadsheet. It honours the same
foliage / rain / clutter / DSM settings as the profile study.

## 4b. Best-site search

`POST /api/rf/site-search` ranks an *n × n* grid of candidate TX positions
over a bounding box (2×2 to 7×7) by coarse served-area fraction — the "where
should the mast go?" question. It uses low-resolution sweeps to stay
interactive; re-run the winning coordinate through full coverage. Both batch
and site-search are Pro-tier features in SaaS mode.

---

## 5. Area coverage simulation

**Run coverage** sweeps a polar grid outward from the TX and paints a
margin-classed raster on the map.

### Parameters

| Setting | Range | Default | Notes |
|---|---|---|---|
| Radius | 0.1–150 km | 10 | simulation extent |
| Radials | 36–720 | 180 | angular resolution |
| Steps per radial | 20–400 | 100 | range resolution |
| Raster size | 128–1,024 px | 512 | output image resolution |
| Antenna | omni / sector / uploaded MSI pattern | omni | see [§7](#7-antenna-patterns) |
| Azimuth | 0–360° | — | sector/MSI pointing |
| H-beamwidth | 5–360° | 65 | parametric sector (-3 dB) |
| V-beamwidth | 1–90° | 10 | parametric vertical cut |
| Downtilt | −10…+20° | 0 | mechanical tilt (MSI electrical tilt is read from the file) |
| Shadow-fade margin | 0–30 dB | 0 | subtracts a log-normal fade allowance from every pixel — design to 90/95 % area |
| Foliage / rain / clutter / k-factor | as in §4 | | applied per-step |
| Surface model | on/off | off | needs `AM_DSM_URL`; buildings become obstructions |

### Output

- **Raster overlay** with 5 margin classes (strong → marginal), transparent
  where unserved; legend included.
- **Served-area fraction**, area-weighted (annulus-correct, not pixel-count).
- Peak/edge statistics: TX ground elevation, strongest RX power, radius.
- **Exports**: PNG (georeferenced bounds), **GeoTIFF** (EPSG:4326, imports
  directly into QGIS / ArcGIS / Atoll / Pathloss) and **KMZ** (Google Earth
  GroundOverlay).

Per-step terrain diffraction uses the vectorized single-strongest-edge
kernel, numerically verified against the float64 reference to < 0.05 dB.
A 10 km, 180×100 sweep completes in ~2–3 s with a warm DEM cache.

---

## 6. Multi-site best-server maps

Enterprise-tier feature. Build a site list and composite them:

1. Configure a TX (position, antenna, azimuth, downtilt) and click
   **Add current TX as site** — repeat for up to **8 sites**.
2. **Best-server map** runs a full coverage simulation per site and paints
   each pixel in the color of the strongest serving site (colorblind-safe
   palette).
3. Per-site **best-server shares** and a combined served fraction are shown;
   the raster is exportable like single-site coverage.

### SINR / interference analysis

Every multi-site run (2+ sites) also computes a **co-channel SINR map**:
per pixel, `SINR = S / (I + N)` where S is the best server, I the linear sum
of every other site heard there (worst-case frequency-reuse-1 — all sites on
the same carrier) and N the thermal noise floor
(`−174 + 10·log₁₀(BW) + NF`, taken from the preset's channel parameters or
the request's `bandwidth_mhz` / `noise_figure_db`; a 10 MHz / 7 dB default is
used — and flagged in a warning — when neither is available).

The panel gains a **Best server / SINR** view toggle plus three statistics:
mean SINR over the served area, % of area at ≥ 6 dB (comfortable MCS), and
the cell-edge fraction below 0 dB. The SINR raster has its own 5-class
green-to-amber legend and PNG URL. Set `interference: false` in the API call
to skip it.

Multi-site accepts the same physics settings as single-site (radials capped
at 360, steps at 200 per site; raster up to 1,024 px on the union bbox).

---

## 7. Antenna patterns

Three ways to model the TX antenna:

1. **Omni** (default) — gain applied uniformly.
2. **Parametric 3GPP sector** — set azimuth, horizontal beamwidth (-3 dB),
   vertical beamwidth and downtilt. Pattern: `12·(Δ/BW)²` capped at 25 dB
   front-to-back horizontally and a 20 dB floor vertically.
3. **Measured MSI Planet file** — upload a `.msi`/`.pln`/`.txt` pattern
   (≤ 2 MB). Gain is converted dBd→dBi (+2.15) automatically; electrical tilt
   read from the header; attenuation is the sum of the H and V cuts. Uploaded
   patterns are listed with gain and -3 dB beamwidths and are private to your
   account when signed in.

---

## 8. Indoor & underground studio

Open **Indoor / Underground** for the three tabs of studies no DEM-based tool
can run. Pro-tier feature in SaaS mode.

### Tab 1 — Floor plan / mine map coverage

Uses a DXF as *structure*, not relief — no georeferencing needed; everything
runs in drawing coordinates.

1. Upload a floor plan (walls read from LINE, LWPOLYLINE, POLYLINE,
   ARC/CIRCLE — arcs tessellated at 15°).
2. Assign a **material per layer** — layer names are auto-guessed against the
   12-material library ([§15](#15-reference-materials--presets)); mark
   decorative layers as *Ignore*.
3. Set the **unit scale** (meters per drawing unit), frequency (or a preset),
   TX/RX heights (default 2.5 m / 1.2 m) and the grid resolution
   (50–400 px, default 200).
4. **Multi-floor** (optional): set *Floors crossed* (0–30) when the TX sits
   N storeys away from the floor you mapped. The engine adds the COST-231
   floor-penetration term `Lf · n^((n+2)/(n+1) − 0.46)` — per-slab loss
   configurable (default 18.3 dB ≈ concrete slab), saturating with n because
   energy increasingly leaks via stairwells/windows — and stretches the 3D
   distance by the storey height. The P.1238 fallback honors the floor count
   too.
5. **Click the rendered plan** to place the TX — or type exact plan X/Y.

The engine computes FSPL over 3D distance **plus the sum of wall crossings**
(COST-231 multi-wall; exact vectorized segment-intersection tests) for every
grid cell, and composites a heatmap with the walls drawn on top. Statistics:
served %, RX power dynamic range. If **no walls** are found on the selected
layers, it automatically falls back to **ITU-R P.1238** site-general indoor
loss and says so in a warning. Export: heatmap PNG.

### Tab 2 — Tunnel / mine gallery link

Emslie waveguide model — reproduces why UHF outranges VHF underground.

| Setting | Range | Default |
|---|---|---|
| Frequency | > 0 MHz | 446 |
| Tunnel width / height | 0.5–30 m | 4 / 3 |
| Length | 10–50,000 m | 2,000 |
| Wall preset | concrete, rock, coal, limestone, salt (εr 4–7) | rock |
| Polarization | horizontal / vertical | horizontal |
| Roughness | 0–1 m | 0.1 |
| Tilt | 0–10° | 0 |
| TX power / gains / losses / sensitivity | free | 30 dBm / 6 dBi / 0 / 0 / −100 dBm |

Output: RX-power-vs-distance chart, attenuation in dB/m, the modal
**breakpoint** (before it the direct ray dominates; after it the guided mode),
and maximum range vs sensitivity.

### Tab 3 — Through-the-earth (TTE)

VLF magnetic-loop link through conductive ground (mine emergency comms).

| Setting | Range | Default |
|---|---|---|
| Frequency | 10 Hz–1 MHz | 5,000 Hz |
| Depth | 1–2,000 m | 100 |
| Ground preset | dry rock (0.001 S/m) → wet clay (0.1 S/m) | average soil (0.01) |
| TX power / system gain / sensitivity | free | 30 dBm / 20 dB / −130 dBm |

Output: **skin depth**, ground attenuation vs near-field spreading split,
total loss, margin and verdict.

---

## 9. Reading the profile chart

- **Terrain fill** — blue = SRTM samples, orange = DXF samples (blend zone
  shades between). Elevations are drawn on the k-curved earth.
- **Green line** — line of sight TX→RX.
- **Dashed line** — lower edge of the first Fresnel zone; terrain intruding
  past it costs diffraction loss even with visual LOS.
- **Red dot** — worst obstruction (highest knife-edge ν).
- **Tooltip** — per-sample elevation, data source, LOS height, Fresnel edge
  and (with a technology selected) received power in dBm.
- Charts longer than 512 samples are downsampled for rendering with a
  peak-preserving algorithm (obstacle peaks are never smoothed away);
  exports always contain every sample.

---

## 10. Accounts, roles & dashboards

Accounts are optional in open mode (see `AM_SAAS_MODE` in
[§17](#17-server-configuration-environment-variables)). Sign in from the
planner header. Registration asks for email, password, organization, **role**
and starting tier.

| Role | Dashboard | Built for |
|---|---|---|
| **Manager** (Enterprise IT) | `/dashboard` — Command Center | project portfolio CRUD, cost/ROI estimator KPIs, plan management, white-label logo upload, org **audit log** |
| **Field technician** | `/field` — Tactical View | forced dark theme, live GPS follow with spot elevation checks, one-tap technology presets that seed the planner |
| **Pre-sales** | `/pitch` — Pitch Interface | A/B scenario comparison with async jobs + progress bars, ROI calculator (payback, 5-yr net), executive PDF |

All three link back to the planner; the role only picks the default landing
experience — nothing is locked away by role (tiers do that, [§12](#12-subscription-tiers)).

Security properties you get for free: PBKDF2-SHA256 passwords (200k
iterations), 30-day bearer tokens with logout revocation, login lockout
(8 failures / 15 min), resource ownership (your DXFs and antenna patterns are
yours), org-scoped audit trail.

---

## 11. Projects, sharing & reports

### Projects

**Save as project** snapshots the entire planner state (endpoints, study
settings, DXF reference, sites) into a named workspace. From the dashboard
(or the API) you can list, rename, duplicate and delete projects; opening
`/?project=ID` restores one exactly. Quotas per tier: 3 / 25 / unlimited.

### Sharing

**Share** creates a public read-only token URL for a project (the token is
stripped from responses of anyone but the owner). Anyone with the link can
view — revoke by deleting the project.

### PDF reports

`POST /api/saas/report.pdf` (or the *Executive PDF* button in the Pitch
dashboard) renders a branded report: link-budget matrix (with environmental
loss lines), the terrain profile chart, coverage raster and a
CAPEX/OPEX/5-year-TCO bill of materials. Enterprise accounts with an uploaded
logo (PNG/JPEG ≤ 1 MB) get **white-label** branding.

### Cost estimator & hardware BOM

`GET /api/saas/costs?technology=…&sites=…` — per-technology BOM (radio,
antenna, install, licensing…) with CAPEX, yearly OPEX and 5-year TCO used by
the dashboard and pitch ROI views. The Command Center's **Bill of materials
(CSV)** link (`GET /api/saas/bom.csv`) downloads the same BOM with line items
scaled to the fleet plus CAPEX/OPEX/TCO summary rows — the procurement
deliverable for a purchase order.

### Field use & offline (PWA)

AntennaMaster is an installable progressive web app. A service worker caches
the app shell, every map tile you've viewed, and your last API results, so the
tool keeps working **off-grid** — the decisive requirement for open-pit,
underground and remote last-mile sites. The **Tactical view** (`/field`) shows
a live **online / offline** indicator; when offline it falls back to cached
tiles and results. Add it to a phone's home screen from the browser's
"Install app" / "Add to Home Screen" menu. (The service worker activates in
production builds only.)

### Async jobs

Long simulations can run as background jobs (`POST /api/saas/coverage/async`
→ `GET /api/saas/jobs/{id}` with live progress %). At most **4 jobs** run
concurrently; a 5th returns HTTP 429 — retry after one finishes.

---

## 12. Subscription tiers

| | **Basic** $0/mo | **Pro** $79/mo | **Enterprise** $299/mo |
|---|---|---|---|
| Global SRTM terrain, all map providers | ✓ | ✓ | ✓ |
| Consumer presets (Wi-Fi, PMR, broadcast, cellular, IoT) | ✓ | ✓ | ✓ |
| Saved projects | 3 | 25 | unlimited |
| **DXF terrain fusion** | — | ✓ | ✓ |
| **PtP backhaul preset (18 GHz)** with rain & gas | — | ✓ | ✓ |
| **Indoor / underground studio** | — | ✓ | ✓ |
| **PDF reports** | — | ✓ | ✓ (white-label) |
| **Private LTE B48 / NR n77 / LTE-M presets** | — | — | ✓ |
| **Multi-site best-server** | — | — | ✓ |
| **API tokens** | — | — | ✓ |

Feature keys (for the API): `srtm_terrain`, `wifi_presets` → basic;
`dxf_fusion`, `ptp_backhaul`, `pdf_export`, `indoor_studio` → pro;
`private_networks`, `multi_site`, `api_access`, `white_label` → enterprise.

In **open mode** (default, `AM_SAAS_MODE` unset) nothing is gated and no
account is required. In **SaaS mode** a gated call without the right tier
returns HTTP **402** with the feature name and required tier. Tier changes
are applied by a billing webhook (`POST /api/auth/tier` with
`X-Billing-Secret`), not by the user directly.

---

## 13. Reference: technology presets

All fields overridable per study. Operators can merge extra band plans from
`DATA_DIR/technologies.json` without code changes (new keys must carry the
full field set).

| Key | Preset | MHz | Default model | Env | TX dBm | TXg dBi | RXg dBi | Losses dB | Sens dBm | TX h / RX h (m) |
|---|---|---|---|---|---|---|---|---|---|---|
| `gsm900` | GSM 900 (2G) | 945 | Okumura-Hata | suburban | 43 | 15 | 0 | 3 | −102 | 30 / 1.5 |
| `gsm1800` | GSM 1800/DCS (2G) | 1842 | COST-231 | urban | 43 | 17 | 0 | 3 | −102 | 30 / 1.5 |
| `umts900` | UMTS 900 (3G) | 942.5 | Okumura-Hata | suburban | 43 | 15 | 0 | 3 | −117 | 30 / 1.5 |
| `umts2100` | UMTS 2100 (3G) | 2140 | 38.901 UMa | nlos | 43 | 18 | 0 | 3 | −117 | 30 / 1.5 |
| `lte800` | LTE 800/B20 (4G) | 806 | Okumura-Hata | suburban | 46 | 15 | 0 | 3 | −105 | 30 / 1.5 |
| `lte1800` | LTE 1800/B3 (4G) | 1842.5 | COST-231 | urban | 46 | 17 | 0 | 3 | −103 | 30 / 1.5 |
| `lte2600` | LTE 2600/B7 (4G) | 2655 | 38.901 UMa | nlos | 46 | 18 | 0 | 3 | −100 | 30 / 1.5 |
| `nr700` | 5G NR n28 700 MHz | 758 | Okumura-Hata | suburban | 46 | 15 | 0 | 3 | −105 | 30 / 1.5 |
| `nr3500` | 5G NR n78 3.5 GHz | 3550 | 38.901 UMa | nlos | 49 | 24 | 0 | 3 | −100 | 25 / 1.5 |
| `nr28000` | 5G NR n257 28 GHz mmWave | 28000 | 38.901 UMi | nlos | 40 | 30 | 10 | 2 | −95 | 10 / 1.5 |
| `pmr446` | PMR446 handheld | 446.1 | Okumura-Hata | open | 27 | 0 | 0 | 0 | −119 | 30 / 1.5 |
| `tetra400` | TETRA 400 (PPDR) | 420 | Okumura-Hata | suburban | 44 | 9 | 0 | 2 | −112 | 40 / 1.5 |
| `vhf150` | VHF land mobile 150 | 155 | Okumura-Hata | open | 44 | 3 | 0 | 1.5 | −116 | 40 / 1.5 |
| `fm100` | FM broadcast 87–108 | 100 | FSPL | open | 60 | 6 | 0 | 1.5 | −90 | 100 / 10 |
| `dvbt600` | DVB-T/T2 UHF 600 | 600 | Okumura-Hata | open | 63 | 10 | 12 | 3 | −84 | 150 / 10 |
| `wifi2400` | Wi-Fi 2.4 GHz outdoor | 2442 | 38.901 UMi | nlos | 20 | 8 | 2 | 1 | −82 | 10 / 1.5 |
| `wifi5800` | Wi-Fi 5.8 GHz PtMP | 5800 | 38.901 UMi | los | 23 | 16 | 14 | 1 | −80 | 20 / 5 |
| `lora868` | LoRaWAN 868 (IoT) | 868 | Okumura-Hata | suburban | 14 | 3 | 0 | 0.5 | −137 | 25 / 1.5 |
| `ptp18000` † | Microwave PtP 18 GHz | 18000 | FSPL | los | 20 | 38 | 38 | 2 | −70 | 30 / 30 |
| `private_lte_b48` ‡ | Private LTE B48/CBRS | 3625 | 38.901 UMa | nlos | 40 | 15 | 0 | 1 | −102 * | 15 / 1.5 |
| `private_nr_n77` ‡ | Private 5G NR n77 100 MHz | 3900 | 38.901 UMa | nlos | 47 | 24 | 0 | 1 | −95 * | 15 / 1.5 |
| `private_lte_iot` ‡ | Private LTE-M/NB-IoT 1.4 MHz | 3625 | 38.901 UMa | nlos | 40 | 15 | 0 | 1 | −120 * | 15 / 1.5 |
| `custom` | Custom study | 446 | FSPL | open | 30 | 0 | 0 | 0 | −100 | 20 / 1.5 |

† Pro tier in SaaS mode · ‡ Enterprise tier in SaaS mode ·
\* channel-aware: sensitivity recomputed from bandwidth (20 / 100 / 1.4 MHz),
noise figure (7 dB) and target SINR (−3 / −3 / −6 dB); MIMO gain
(3 / 6 / 0 dB) added to the budget.

---

## 14. Reference: propagation models

| Key | Model | Valid frequency | Environments | Typical use |
|---|---|---|---|---|
| `fspl` | Free space (ITU-R P.525) | 1 MHz–300 GHz | — | baseline, microwave PtP |
| `okumura_hata` | Okumura-Hata | 150–1,500 MHz | urban, suburban, open | GSM900, TETRA, PMR, FM/TV |
| `cost231_hata` | COST-231 Hata | 1,500–2,000 MHz | urban, metropolitan, suburban, open | GSM1800/DCS, UMTS2100 |
| `tr38901_rma` | 3GPP TR 38.901 RMa | 0.5–30 GHz | los, nlos | 4G/5G rural macro |
| `tr38901_uma` | 3GPP TR 38.901 UMa | 0.5–100 GHz | los, nlos | LTE / 5G urban macro |
| `tr38901_umi` | 3GPP TR 38.901 UMi | 0.5–100 GHz | los, nlos | small cells, mmWave street |

All models are floor-bounded by FSPL. Out-of-validity inputs are clamped and
a warning is attached to the response. **Deygout multi-knife-edge terrain
diffraction** (≤ 3 edges, ITU-R P.526) is always added on top, computed on
the k-curved fused profile.

Environmental add-ons (any model): Weissberger foliage (0–400 m),
ITU-R P.838-3/P.530 rain fade (specific attenuation × effective path length),
ITU-R P.676-style gaseous absorption (oxygen 60 GHz / water-vapor 22 GHz
lines — automatic, significant only for high-frequency PtP), and
**ITU-R P.2108 §3.2 statistical clutter** — the man-made land-use loss the
DEM cannot see, at a settable percentage of locations (50 = median,
90 = conservative; defined 0.5–67 GHz, sub-500 MHz requests use the 0.5 GHz
curve with a warning).

Indoor/underground models: COST-231 multi-wall, ITU-R P.1238, Emslie tunnel
waveguide, TTE skin-depth — see [§8](#8-indoor--underground-studio).

---

## 15. Reference: materials & presets

### Wall materials (dB per crossing, log-frequency interpolated)

| Material | 900 MHz | 2.4 GHz | 5.8 GHz |
|---|---|---|---|
| Drywall / plasterboard | 2 | 3 | 4 |
| Wood / door | 3 | 4 | 6 |
| Glass (plain) | 1.5 | 2 | 3 |
| Glass (low-E coated) | 10 | 12 | 15 |
| Brick wall | 6 | 8 | 12 |
| Concrete 20 cm | 10 | 13 | 20 |
| Reinforced concrete 30 cm+ | 18 | 23 | 32 |
| Metal / shielding | 26 | 30 | 35 |
| Rock pillar (mine) | 25 | 35 | 45 |
| Earth / backfill | 30 | 45 | 60 |
| Elevator / machinery | 20 | 25 | 30 |
| Ignore (decorative layer) | 0 | 0 | 0 |

### Tunnel wall presets (relative permittivity εr)

concrete 6.0 · hard rock (granite) 5.0 · coal 4.0 · limestone 7.0 · salt 4.5

### Earth conductivity presets (S/m)

dry rock/granite 0.001 · limestone (karst) 0.005 · average soil 0.01 ·
coal measures 0.02 · wet soil/clay 0.1

---

## 16. Reference: every setting

Consolidated list of every user-adjustable parameter with its valid range.

### Path & profile (`GET /api/terrain/profile`, planner sidebar)

| Parameter | Range | Default |
|---|---|---|
| TX/RX lat, lon | ±90 / ±180 | — |
| TX height / RX height (m AGL) | ≥ 0 | 20 / 10 |
| Samples | 16–2,048 | 256 |
| k-factor | 0.1–10 | 4/3 |
| technology / model / environment | see §13–14 | — |
| freq_mhz | > 0 | preset (else 446) |
| tx_power_dbm, tx_gain_dbi, rx_gain_dbi, losses_db, rx_sensitivity_dbm | free | preset |
| foliage_depth_m | 0–400 | 0 |
| rain_rate_mm_h | 0–150 | 0 |
| clutter_pct | 0–99.9 (0 = off) | 0 |
| surface | true/false (needs `AM_DSM_URL`) | false |
| dxf_id | georeferenced DXF | none (SRTM only) |

### Coverage (`POST /api/rf/coverage`)

| Parameter | Range | Default |
|---|---|---|
| radius_km | 0.1–150 | 10 |
| n_radials | 36–720 | 180 |
| n_steps | 20–400 | 100 |
| raster_px | 128–1,024 | 512 |
| antenna_azimuth_deg | 0–360 | omni |
| antenna_beamwidth_deg | 5–360 | 65 |
| vertical_beamwidth_deg | 1–90 | 10 |
| downtilt_deg | −10–+20 | 0 |
| antenna_id | uploaded MSI id | — |
| shadow_margin_db | 0–30 | 0 |
| k_factor | 0.1–10 | 4/3 |
| foliage_depth_m / rain_rate_mm_h | 0–400 / 0–150 | 0 / 0 |
| clutter_pct | 0–99.9 | 0 |
| surface | true/false | false |
| + all link-budget overrides from §4 | | |

### Multi-site (`POST /api/rf/coverage/multi`)

Same as coverage, except: `sites` 1–8 (each with lat/lon, azimuth,
downtilt, optional antenna), `n_radials` 36–360 (default 120), `n_steps`
20–200 (default 80), `raster_px` default 768. SINR analysis:
`interference` (default true), `bandwidth_mhz` (0–400, else preset/10),
`noise_figure_db` (0–20, else preset/7).

### Batch receivers (`POST /api/rf/batch`)

`lat`/`lon` (TX), `receivers` 1–200 (each `lat`, `lon`, optional `name`,
`rx_height_m`), `technology`, `dxf_id`, `surface`, `k_factor`,
`foliage_depth_m`, `rain_rate_mm_h`, `clutter_pct`, and the same link-budget
overrides as coverage. `?format=csv` for a CSV download.

### Best-site search (`POST /api/rf/site-search`)

`south`/`west`/`north`/`east` bbox, `grid_n` 2–7 (default 5), `technology`,
`radius_km` 0.1–50, `shadow_margin_db`, `clutter_pct`, `k_factor`, `dxf_id`,
`surface`, and TX-side budget overrides.

### Height optimizer (`GET /api/terrain/optimize-heights`)

`lat1`/`lon1`/`lat2`/`lon2`, `tx_height_m`, `rx_height_m`, `freq_mhz` or
`technology`, `k_factor`, `max_height_m` (1–500, default 120), `dxf_id`,
`surface`.

### Indoor coverage (`POST /api/indoor/coverage`)

| Parameter | Range | Default |
|---|---|---|
| unit_scale (m per drawing unit) | > 0 | 1 |
| layer→material map | §15 | auto-guessed |
| tx_x, tx_y (drawing coords) | in plan | click |
| tx_height_m / rx_height_m | > 0 | 2.5 / 1.2 |
| floors_crossed | 0–30 | 0 |
| floor_height_m | 2–6 | 3 |
| floor_loss_db | 0–40 | 18.3 |
| grid_px | 50–400 | 200 |
| freq_mhz or technology | > 0 | preset |
| tx_power_dbm etc. | free | preset |

### Tunnel (`GET /api/indoor/tunnel`)

freq > 0 (446) · width 0.5–30 m (4) · height 0.5–30 m (3) ·
length 10–50,000 m (2,000) · wall preset (rock) · polarization h/v ·
roughness 0–1 m (0.1) · tilt 0–10° (0) · budget terms free.

### TTE (`GET /api/indoor/tte`)

freq 10 Hz–1 MHz (5,000) · depth 1–2,000 m (100) · earth preset
(average_soil) · tx_power_dbm (30) · system_gain_db (20) ·
rx_sensitivity_dbm (−130).

### Georeferencing (`POST /api/dxf/{id}/georeference`)

mode `known_crs` (epsg/proj string) | `control_points` (2–3 pairs) |
`origin_bearing` (lat, lon, bearing 0–360, unit scale, offsets) ·
z_scale free (default follows horizontal) · layer selection.

### UI-only settings

Base layer + custom XYZ URL · theme (auto/dark/light) · fade margin ·
search · GPS · swap ends · sites list · project save/load.

---

## 17. Server configuration (environment variables)

All backend behavior is tunable via `AM_*` environment variables — no code
edits needed.

| Variable | Default | Purpose |
|---|---|---|
| `AM_DATA_DIR` | `backend/data` | root for DEM cache, DXF store, results, SQLite DB |
| `AM_DEM_URL` | AWS Terrarium template | any Terrarium-encoded XYZ elevation source |
| `AM_DEM_ZOOM` | 12 (≈ 38 m/px) | DEM tile zoom; higher = finer + more tiles |
| `AM_DSM_URL` | unset | optional Terrarium-encoded **surface model** source (buildings/canopy); enables `surface=true` on profiles and coverage |
| `AM_BASEMAP_URL` | OSM | source for the local base-map tile server (`/api/basemap`) used for offline maps |
| `AM_DEM_CACHE_MB` | 2048 | disk budget for the tile cache (LRU-evicted) |
| `AM_FEATHER_CELLS` | 3.0 | width of the DXF↔SRTM blending band, in grid cells |
| `AM_VALIDATION_DIFF_M` | 50.0 | mean-elevation mismatch that triggers the strict warning |
| `AM_MAX_DXF_MB` | 100 | DXF upload cap |
| `AM_CORS_ORIGINS` | `*` | comma-separated allowed origins |
| `AM_SAAS_MODE` | unset (open) | `1` = enforce accounts, tiers and quotas |
| `AM_BILLING_SECRET` | unset | shared secret required by the tier-change webhook in SaaS mode |

Frontend: `BACKEND_URL` (default `http://localhost:8010`) — where the
Next.js server proxies `/api/*`.

Operator band plans: drop a `technologies.json` into `AM_DATA_DIR` to merge
custom presets (each new key needs the complete field set; existing keys are
never overridden).

---

## 18. Limits & capacities

| Resource | Limit |
|---|---|
| DXF upload | 100 MB (configurable) |
| MSI antenna file | 2 MB |
| White-label logo | 1 MB (PNG/JPEG) |
| DXF terrain grid | ≤ 400×400 cells |
| Profile samples | ≤ 2,048 |
| Coverage sweep | ≤ 720 radials × 400 steps, ≤ 150 km radius |
| Coverage raster | ≤ 1,024 px |
| Sites per composite | 8 |
| Indoor grid | ≤ 400 px |
| Concurrent async jobs | 4 (429 beyond) |
| Stored raster results | last 200 (disk, auto-pruned; any worker serves any result) |
| DEM RAM cache | 2,000 decoded tiles |
| Saved projects | 3 / 25 / ∞ by tier |
| Session tokens | 30-day TTL, revoked on logout |
| Login lockout | 8 failures / 15 minutes |
| Benchmark gates (CI) | every endpoint scenario < 5 s, < 1 GB — see `QA_BENCHMARK_REPORT.md` |

Verified by 100 backend test cases + 10 frontend tests (`./start.sh --check`).

## 19. Troubleshooting

| Symptom | Cause & fix |
|---|---|
| *"DXF mean elevation differs from SRTM by X m"* warning | almost always feet-vs-meters (set unit scale / `z_scale` 0.3048) or a wrong EPSG code — check Helmert residuals |
| Large Helmert residuals (m) | one control point is misidentified; re-pick it |
| HTTP **402** on an endpoint | feature is tier-gated in SaaS mode — response says which tier unlocks it |
| HTTP **429** on async coverage | 4 jobs already running; wait and retry |
| HTTP **429** on login | lockout after 8 failed attempts — wait 15 min |
| HTTP **502** from terrain endpoints | DEM tile source unreachable — check internet / `AM_DEM_URL` |
| Place search does nothing | Nominatim geocoding needs internet; `lat, lon` entry always works offline |
| Coverage looks too optimistic | add a shadow-fade margin (5.5 dB ≈ 90 %, 8 dB ≈ 95 % area), enable P.2108 clutter for built-up areas, and check the environment setting (nlos vs los) |
| 422 "No surface model configured" | `surface=true` needs `AM_DSM_URL` pointing at a Terrarium-encoded DSM tile source |
| SINR warning about assumed receiver | the preset has no channel parameters — pass `bandwidth_mhz` / `noise_figure_db` in the multi-site request |
| Indoor heatmap ignores walls | selected layers had no line entities — the P.1238 fallback warning tells you; check layer selection and material mapping |
| Profile chart looks flat under the LOS line | you may be zoomed on a long path — hover the worst-obstruction dot; the chart is k-curved, terrain drops with distance |
| Model warning about frequency | you're outside the model's validity range — the value was clamped; pick a suitable model from §14 |

Known modeling boundaries (by design, documented in `docs/CAPABILITIES.md`):
median empirical models + knife-edge diffraction (no ITM/P.1546/P.452 —
Deygout + the Hata/38.901 family covers the same planning use cases);
clutter is statistical (ITU-R P.2108), not a per-pixel land-use database;
SINR assumes worst-case co-channel reuse-1 (no frequency plan / scheduler);
multi-floor is a penetration term, not per-floor wall maps; building
obstruction needs a user-supplied DSM tile source (`AM_DSM_URL`).

---

## 20. Advanced modules, 3D digital twin & live operations

Beyond predicting coverage, AntennaMaster now *designs*, *certifies* and
*operates*. Open **Advanced studies** from the planner for the link-level tools;
the 3D view, Live Operations and LiDAR are described below. Full endpoint
reference: `VISION_ARCHITECTURE.md` and the OpenAPI page.

### Two-way "talk-back" (land-mobile radio)

A radio system is limited by the *weaker* of two directions. The two-way tool
computes **talk-out** (base → portable) *and* **talk-in** (portable → base),
grades each in **DAQ** (Delivered Audio Quality, TIA-4046) and reports the
limiting direction and the reliable talk-back area. It models portable **body
loss** and a **penetration class** (on-street / in-vehicle / in-building /
underground), and a **repeater-cascade** solver returns the spacing and count
for continuous corridor coverage.

| Endpoint | Purpose |
|---|---|
| `POST /api/rf/twoway/link` | bidirectional link verdict (talk-out/talk-in, DAQ, limiting direction) |
| `POST /api/rf/twoway/coverage` | area study: talk-out / talk-in / reliable-both served fractions |
| `POST /api/rf/twoway/repeater-cascade` | repeater count & spacing for a corridor |

### Leaky feeder & distributed antennas (metro / mine)

The real way tunnels are covered — a **radiating (leaky) coaxial cable** or a
**distributed antenna system**. The tool models cable longitudinal + coupling
loss, solves **inline-amplifier spacing**, adds bend loss, and reports served
length and worst uncovered gap; the DAS designer turns the Emslie single-antenna
reach into an antenna count and spacing.
`POST /api/indoor/leaky-feeder` · `GET /api/indoor/tunnel-das`.

### Automated AP placement (campus / warehouse)

The inverse of the heatmap: given a floor plan and a coverage (and optional
capacity) target, `POST /api/indoor/auto-place` returns **how many** access
points, **where**, and on **which channel** — greedy maximum-coverage placement
over the same multi-wall engine, a graph-colour channel plan (2.4 / 5 / 6 GHz),
a users × throughput capacity floor and a −67 dBm roaming-overlap check.

### RF-exposure / EMF compliance

`POST /api/rf/compliance` computes **ICNIRP** or **FCC OET-65** public and
occupational exclusion-zone distances and the exposure ratio at a given
distance — the permitting gate before an antenna is switched on.

### Longley-Rice (ITM) with a reliability quantile

`GET /api/terrain/itm` adds an **Irregular Terrain Model** path loss that
delivers a *reliability quantile* (fraction of time and situations), not just a
median — the statistical model empirical curves lack. It combines the validated
Deygout diffraction with the Longley-Rice terrain-roughness statistic and the
ITM time/situation variability.

### Drive-test calibration

`POST /api/rf/calibrate` fits an offset (and optional distance-slope) correction
from **measured RSSI** versus prediction and reports the RMS error before and
after — turning predictions into site-tuned, trusted predictions.

### AI design copilot

`POST /api/copilot/analyze/link` runs the profile **and** the height optimizer,
then explains the result as ranked, actionable findings with a **quantified
fix** (raise the mast to X m, add Y dB, change band, add a repeater). It is
deterministic and works offline; an optional Claude narrator adds prose when an
API key is present. `GET /api/copilot/tools` publishes a machine-readable tool
catalog so an external agent can drive the simulator.

### 3D digital twin (CesiumJS)

A seamless **2D / 3D** toggle on the map renders the fused SRTM+DXF terrain in a
WebGL globe — fed by the platform's own heightmap tiles
(`GET /api/terrain/heightmap/{z}/{x}/{y}.bin`, no Cesium Ion key, offline-capable).
It draws a glowing 3D **Fresnel tube** along the true line of sight, red markers
where terrain slices into the Fresnel zone, and drapes the coverage heatmap over
the 3D relief.

### Live Operations (digital-twin telemetry)

The **Live Operations** dashboard (`/live`) ingests real-time asset positions
from fleet-management or IoT feeds (`POST /api/telemetry/ingest`, WebSocket
`/api/telemetry/ws`) and streams the live twin over Server-Sent Events
(`/api/telemetry/stream`). Each asset is correlated against the RF prediction:
it flashes **yellow** on entering a predicted **dead zone**, and an
**RF-disconnect** event is logged (with whether the last position was in a dead
zone) when it stops transmitting. Bind the prediction with
`POST /api/telemetry/coverage-context`.

### Drone LiDAR / point-cloud ingestion

`POST /api/lidar/upload` ingests a `.las`/`.laz` survey and rasterises it into a
**Digital Surface Model** that overrides the statistical clutter, so diffraction
is computed against the **real surveyed buildings, trees and machinery**.
`GET /api/lidar/{id}/profile` returns a surveyed-surface-vs-bare-terrain
comparison (validated: a 50 m building raised a link's modelled diffraction from
40 dB to 114 dB).
