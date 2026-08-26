# AntennaMaster — Complete Functionality, Capability & Capacity Reference

Verified against the codebase: **86 REST/stream endpoints** (66 simulation +
20 SaaS/accounts), **256 backend test functions (266 cases)** + 13 frontend
component tests. Companion docs: `VISION_ARCHITECTURE.md` (3D digital twin, live
telemetry, LiDAR), `ROADMAP.md` (five-layer capability model & delivered
phases), `ASSESSMENT.md` (benchmark & review history), `SaaS_ARCHITECTURE.md`
(accounts, tiers, workspaces, monetization).

## 1. Terrain engine

| Capability | Detail |
|---|---|
| Global elevation | Mapzen/AWS **Terrarium** RGB tiles (SRTM-derived, ~30 m), any Terrarium-encoded XYZ source via `AM_DEM_URL`; zoom configurable (`AM_DEM_ZOOM`, default 12 ≈ 38 m/px) |
| Surface model (DSM) | optional second Terrarium source via `AM_DSM_URL` (buildings/canopy included); any profile or coverage request can pass `surface=true` to treat them as obstructions |
| Tile caching | Two-tier: decoded-tile RAM LRU (2,000 tiles ≈ 500 MB cap) + on-disk Z/X/Y PNG cache with mtime-LRU eviction to `AM_DEM_CACHE_MB` (default 2 GB); atomic writes; download-once semantics |
| Sampling | Seamless cross-tile **bilinear** interpolation in global pixel space, vectorized; antimeridian wrap; polar clamp (±85°) |
| Profiles | True **WGS84 geodesic** paths (pyproj), 16–2,048 samples per profile |
| DXF terrain fusion | High-res DXF relief patched over SRTM inside its bounding box; **3-cell feathered blending** (configurable) to prevent false diffraction cliffs; per-sample provenance (`srtm`/`blend`/`dxf`) |
| Validation | DXF vs SRTM mean-elevation cross-check over the same footprint; strict warning above 50 m (`AM_VALIDATION_DIFF_M`) — catches ft/m mix-ups and bad transforms |

## 2. DXF pipeline (dual interpretation)

**As terrain relief:** Z extracted from POINT, LWPOLYLINE (`elevation`
attribute — contours as constant-Z entities), POLYLINE (2D/3D/polyface/
polygon mesh), 3DFACE, MESH, TEXT/MTEXT spot heights (regex-parsed, EL/H=
prefixes); per-layer inventory (entity types, point counts, Z ranges,
terrain-likeness heuristic); scattered cloud → regular grid via
`scipy.griddata` linear with nearest-neighbour edge fallback; grid ≤400×400,
density-aware; XY de-duplication; damaged-file recovery loader.

**As structure (indoor/underground):** LINE, LWPOLYLINE, POLYLINE,
ARC/CIRCLE (15° tessellation) → 2D wall segments with per-layer materials.

**Georeferencing — three modes:**
1. **Known CRS** — any EPSG code / PROJ string via pyproj (UTM, Lambert,
   state plane…), auto meters-per-unit from axis units.
2. **Control points** — 2–3 point 2D **Helmert** (similarity) solved by
   least squares in a local AEQD plane; per-point + RMS **residuals in
   meters** returned; degenerate-input detection.
3. **Origin + bearing** — anchor Lat/Lon, +Y-axis true bearing, unit scale
   (m/ft/yd/cm), origin offset; vertical follows horizontal by default.

All modes bidirectional (exact inverse), vertical `z_scale` independent,
state persisted as a JSON sidecar and deterministically rebuilt by any
worker (`ensure_ready`).

## 3. Propagation models (6 empirical + ITM)

| Model | Range | Use |
|---|---|---|
| Free space (ITU-R P.525) | any | baseline, microwave PtP |
| Okumura-Hata (urban/suburban/open) | 150–1500 MHz | GSM900, PMR, broadcast |
| COST-231 Hata (+metropolitan) | 1500–2000 MHz | GSM1800/DCS |
| 3GPP TR 38.901 RMa LOS/NLOS | 0.5–30 GHz | 4G/5G rural |
| 3GPP TR 38.901 UMa LOS/NLOS | 0.5–100 GHz | 4G/5G urban macro |
| 3GPP TR 38.901 UMi LOS/NLOS | 0.5–100 GHz | small cells, mmWave |
| **Longley-Rice / ITM** | irregular terrain | **reliability-quantile path loss** (`/api/terrain/itm`): validated Deygout median + terrain-roughness Δh + time/situation variability (`qerfi`) |

All floor-bounded by FSPL; out-of-validity inputs clamped with API warnings.
**Terrain diffraction on top of any model:** Deygout multi-knife-edge (≤3
edges, ITU-R P.526 loss, k-curved fused profile, grazing-edge recursion
guard); the **same Deygout construction is vectorized per step in area
coverage** — principal edge plus one secondary on each sub-path — pinned to
the scalar reference by `tests/test_coverage_diffraction.py` (exact agreement
up to two obstructing edges). Area coverage previously used only the strongest
single edge, which measured 15–30 dB optimistic in multi-ridge terrain.

**Indoor/underground models:** ITU-R P.1238 (office/residential/commercial,
floor penetration), COST-231 multi-wall (12-material library, dB/crossing
at 900/2400/5800 MHz, log-f interpolated), Emslie tunnel waveguide
(dominant-mode dB/m from cross-section, εr, roughness, tilt; direct-ray vs
guided-mode dual mechanism, modal breakpoint), through-the-earth VLF
(skin-depth attenuation + near-field 1/r³ induction spreading).

**Environmental excess losses (stack on any model):** Weissberger MED
foliage/vegetation (0.23–95 GHz, 400 m clamp), ITU-R P.838-3 rain
(k·R^α, log-interpolated 1–100 GHz, P.530 effective path), ITU-R P.676-style
atmospheric gases (22/60 GHz lines), **ITU-R P.2108 §3.2 statistical
clutter** (man-made land-use loss at a settable location percentage —
50% median to 90%+ planning margins; distance-dependent, 0.5–67 GHz). **Channel-aware budgets:** sensitivity
derived from kTB + 10log₁₀(BW) + NF + SINR when the preset defines channel
width; MIMO diversity gain in all budgets.

**RF context:** k-factor earth curvature (default 4/3, settable 0.1–10)
applied before all Fresnel/LOS math; Fresnel zone-n radius; knife-edge ν;
3GPP parabolic sector pattern (H 25 dB FTB + V 20 dB floor with
mechanical downtilt) **or measured MSI Planet patterns** (dBd→dBi,
electrical tilt, sum-of-cuts H+V).

## 4. Radio studies (23 technology presets, all fields overridable)

2G GSM 900/1800 · 3G UMTS 900/2100 · 4G LTE 800/1800/2600 · 5G NR n28/n78/
n257 (28 GHz mmWave) · TETRA 400 · PMR446 · FM 87–108 · DVB-T/T2 UHF ·
Wi-Fi 2.4/5.8 · LoRaWAN 868 · 18 GHz PtP backhaul · **Private LTE B48/CBRS · Private 5G NR n77 (100 MHz) · NB-IoT/LTE-M · VHF land mobile 150 MHz** · fully custom.
Presets carry freq/EIRP components/sensitivity/heights/best model; operator
band plans mergeable from `DATA_DIR/technologies.json` without code changes.

**Study types:**
- **Point-to-point link**: fused profile + LOS/Fresnel verdicts, per-sample
  RX power, path-loss/diffraction split, margin vs sensitivity,
  worst-obstruction location + ν.
- **Single-site area coverage**: polar sweep (36–720 radials × 20–400
  steps, ≤150 km radius), per-step diffraction, omni/sector/MSI antennas,
  downtilt, **shadow-fade margin** (design to 90/95% area), area-weighted
  served fraction, margin-classed raster (5 classes, colour-vision-safe
  ColorBrewer RdYlBu scale — blue = strong → red = marginal — transparent
  where unserved). ~2 s for a 10 km 180×100 sweep (cached DEM).
- **Multi-site best-server**: up to 8 sites, per-site azimuth/downtilt,
  strongest-served-signal composite in CVD-safe site colors, per-site
  best-server shares, union-bbox raster.
- **Co-channel SINR / interference**: every multi-site run also computes
  per-pixel SINR = S/(I+N) (worst-case frequency-reuse-1; thermal floor
  from bandwidth+NF, preset-derived or overridable), a 5-class SINR raster,
  mean SINR, %area ≥ 6 dB and cell-edge (<0 dB) fraction.
- **Batch receiver qualification**: one TX vs up to 200 receiver/subscriber
  locations in a single call (fused profile + Deygout + environmental
  losses + margin verdict each), JSON or CSV — the fixed-wireless/WISP
  survey workflow.
- **Best-site search**: rank an n×n grid of candidate TX positions by
  coarse served-area fraction ("where should the mast go?").
- **Antenna height optimizer**: minimum TX/RX height (bisection) for LOS and
  the 60% first-Fresnel rule.
- **Refraction reliability**: dual-k (4/3 & 2/3) Fresnel-clearance verdict on
  every profile — standard microwave dependable-hop practice.
- **Indoor floor-plan coverage**: click-to-place TX on the rendered plan,
  FSPL(3D)+wall crossings per grid cell (vectorized ray/segment tests,
  50–400 px grid), heatmap with walls composited, served %, RX dynamic
  range; **multi-floor**: COST-231 floor-penetration term (non-linear
  saturation, per-slab dB configurable) for TX N storeys from the mapped
  floor — the P.1238 fallback honors the floor count too.
- **Tunnel/mine link**: RX power vs distance chart, α dB/m, breakpoint,
  max range vs sensitivity; wall presets (concrete/rock/coal/limestone/salt).
- **TTE link**: skin depth, ground+spreading loss split, margin/verdict;
  ground presets (dry rock → wet clay, 0.001–0.1 S/m).

## 4b. System design, optimization, compliance & intelligence

Beyond *predicting* coverage, the platform now *designs*, *optimizes*,
*certifies* and *advises* (the Layer 2–5 capabilities — see `ROADMAP.md`):

- **Two-way (LMR) talk-back** (`/api/rf/twoway/*`): talk-out **and** talk-in
  computed together and limited by the weaker direction (by reciprocity the two
  differ only by the TX-power swap, so one downlink sweep yields both); **DAQ**
  (delivered-audio-quality, TIA-4046) grading; portable body loss + penetration
  classes (on-street / in-vehicle / in-building / underground); an area study
  reporting talk-out/talk-in/**reliable-both** served fractions with the
  limiting-direction split; a **repeater-cascade** spacing/count solver for
  continuous corridor talk-back.
- **Leaky feeder & distributed antennas** (`/api/indoor/leaky-feeder`,
  `/tunnel-das`): radiating-cable field profile (longitudinal + coupling loss),
  inline-amplifier spacing solver, bend excess-loss, served-length and
  worst-gap KPIs; a DAS designer turning the Emslie single-antenna reach into
  antenna count + spacing — the real metro / underground-mine deliverable.
- **Automated AP placement** (`/api/indoor/auto-place`): the inverse of the
  heatmap — greedy maximum-coverage set-cover over the same multi-wall
  path-loss model, a graph-colour **channel plan** (2.4/5/6 GHz reuse sets), a
  users×throughput **capacity floor**, and a −67 dBm **roaming-overlap** check.
- **EMF exposure compliance** (`/api/rf/compliance`): ICNIRP and FCC OET-65
  public/occupational exclusion-zone distances and exposure ratios, with an
  optional ground-reflection worst case — the permitting gate.
- **Drive-test calibration** (`/api/rf/calibrate`): fit an offset / offset+slope
  correction from measured RSSI vs prediction and report RMS error before/after
  — turning predictions into site-tuned, trusted predictions.
- **AI design copilot** (`/api/copilot/*`): an engine-driven, **air-gapped**
  advisor that runs the profile + height optimizer and turns the numbers into
  ranked, actionable findings with quantified fixes (mast height, dB deficit,
  band change, repeater); a machine-readable **tool catalog** exposing the
  study endpoints so an external agent (MCP / function-calling) can drive the
  simulator; an optional Claude-backed narrator when an API key is present.

## 4c. 3D digital twin, live telemetry & drone LiDAR

The immersive, operational layer (see `VISION_ARCHITECTURE.md`):

- **3D volumetric rendering (CesiumJS)** — a seamless 2D/3D toggle renders the
  fused SRTM+DXF terrain in a WebGL globe, fed by the platform's OWN heightmap
  tiles (`/api/terrain/heightmap/{z}/{x}/{y}.bin`, no Cesium Ion key, offline-
  capable). Shows a glowing 3D **Fresnel cylinder** along the true LOS, red
  markers where terrain slices into the Fresnel zone, and the coverage heatmap
  draped over the 3D terrain. Cesium loads at runtime (not bundled) and decodes
  in Web Workers so the UI never blocks.
- **Live telemetry / digital twin** — ingest real-time asset positions (POST,
  or WebSocket `/api/telemetry/ws`) and stream the live twin over SSE
  (`/api/telemetry/stream`). Each asset is correlated against the RF prediction:
  **dead-zone entry** flags (evaluated with the planner's own link budget) and
  **RF-disconnect correlation** (logs whether a lost tracker was in a predicted
  dead zone). Live Operations dashboard at `/live`.
- **Drone LiDAR ingestion** — upload a `.las`/`.laz` survey
  (`/api/lidar/upload`); it is rasterised into a Digital Surface Model that
  overrides statistical clutter, so diffraction is computed against the real
  surveyed buildings/trees/machinery (validated: a 50 m building raised a link's
  modelled diffraction from 40 to 114 dB).

## 5. Frontend (Next.js 14 + React-Leaflet + Recharts)

Map: 6 built-in providers (OSM, OpenTopoMap, Carto Light/Dark, Esri
Imagery/Topo) + custom XYZ template; click-to-place TX/RX with typed exact
coordinates, GPS geolocation, swap-ends; place/coordinate search
(Nominatim); DXF footprint polygon + semi-transparent hillshade overlay
(hypsometric tint × analytic hillshade, rotation-safe, auto-fit); coverage
raster overlay with legend.

Profile chart: provenance-colored terrain (blue SRTM / orange DXF, validated
palette), curved-earth display, LOS + first-Fresnel lower edge,
worst-obstruction marker, rich tooltip (elevation, source, LOS, F1, RX power).

Workflows: 3-step DXF wizard (upload → layer select with terrain preselect →
georef modes incl. Helmert residual display); radio-study panel (preset
groups by generation, model/environment override, site link-budget override
panel, antenna pattern upload/select, sites list + best-server run);
indoor/underground studio (3 tabs). Session fully persisted (localStorage +
server-side DXF state restore); dark/light/auto theming; responsive ≤800 px;
debounced recomputes; Escape/aria on modals.

**Onboarding & internationalization (for non-technical operators):**
- **Bilingual UI (English / French)** via react-i18next, persistent locale
  switcher in the header; the framework and `locales/{en,fr}/common.json`
  extend to any locale. Verified that switching does not break Leaflet or
  Recharts.
- **Simple Mode** — a guided toggle that hides dBi/MHz/model and asks "what
  are you trying to connect?" (connect two buildings, Wi-Fi for a vehicle
  fleet, handheld radios across a site, private 4G/5G, IoT, mobile coverage,
  long-distance backhaul). The backend (`/api/rf/scenarios`) maps each
  plain-language outcome to the correct preset + study defaults.
- **Guided tour** (react-joyride) auto-runs once for new users and is
  replayable — placing points, choosing a technology, uploading a DXF,
  reading the heatmap; fully translated.
- **Glossary tooltips** (Radix Tooltip, keyboard-accessible) on every
  technical parameter — plain-language, equation-free, translated.
- **Point inspection on the coverage map** — `GET /api/rf/coverage/{id}/at`
  reports rx power, margin, grade and distance/bearing at any coordinate,
  looked up from the stored polar field with the same indexing that painted
  the raster (so value and colour cannot disagree; pinned by a test that
  samples the PNG and the query together).
- **Customizable sidebar (drag-and-drop)** — an "Arrange panels" mode turns
  every sidebar tool into a draggable card: reorder by dragging the ⠿ handle
  (or ↑/↓ keys, WCAG 2.1.1-safe) and hide the panels you don't use. The layout
  (order + hidden set) persists to localStorage per browser; dependency-free
  native HTML5 DnD, so it works offline. Discoverable via a dedicated tour step.

**Exports / GIS interoperability:** profile CSV, batch-receiver CSV,
line-of-sight **KML/KMZ** (TX/RX placemarks + LoS path + terrain, for Google
Earth / QGIS / ArcGIS), coverage PNG + **GeoTIFF (EPSG:4326)** + KMZ
GroundOverlay, indoor heatmap PNG, hardware **BOM CSV** (fleet-scaled),
branded PDF report. An "Export to GIS" menu surfaces the geospatial formats.

**Hardware Catalog:** 194 equipment profiles across 14 classes (macro antennas,
Massive-MIMO radios, PtP/mmWave, **leaky feeders with real attenuation/coupling
curves**, LMR/TETRA repeaters, tunnel antennas, Wi-Fi 6/6E/7, LTE/5G CPEs,
WISP antennas, LoRaWAN/IoT, GNSS) — **143 of them datasheet-grade, scraped
verbatim from official vendor pages** (MikroTik 87, Ubiquiti 55; per-record
`provenance` + machine-checkable `source_url`), the rest tagged
published_typical / class_reference. CI gates enforce physical-sanity bounds,
traceable provenance and a majority-datasheet floor. An Equipment Selector
auto-fills the RF parameters, and the leaky-feeder studio autofills cable
physics from the catalog. Ingestion pipeline with explicit-evidence dedup
(`tools/ingest_catalog.py`, scrapers `tools/scrape_mikrotik.py` /
`tools/scrape_ubiquiti.py`); extensible via `catalog_sources/` or
`AM_DATA_DIR/hardware_catalog.json`. Audit: `GLOBAL_INVENTORY_AUDIT.md`.

**Field-ready (PWA + offline maps):** installable web app with an offline
service worker (app shell, map tiles, last API results) **plus a local
base-map tile server** (`/api/basemap`) with a pre-download utility
(`tools/download_basemap.py --bbox …`) — the map keeps rendering from cached
OSM tiles when the browser is offline (seamless auto-fallback). The tactical
view shows a live online/offline indicator.

**OT/IT security:** centralized audit middleware records every critical
action (logins, uploads, project changes, all exports) with user id + client
IP to an append-only `audit.log` (0600) and the tenant-scoped DB; confidential
site CAD (`dxf_store/`) and results are stored owner-only (0700), the
credential/audit DB 0600. Full posture: `SECURITY_COMPLIANCE.md`.

## 6. Operations & scale

| Aspect | Capacity / behavior |
|---|---|
| Multi-worker safety | rasters + DXF state disk-backed; any worker serves any result; restart-safe (tested) |
| Result retention | last 200 raster results on disk (auto-pruned) |
| Upload caps | DXF ≤100 MB (`AM_MAX_DXF_MB`), antenna files ≤2 MB |
| Simulation caps | radius ≤150 km, 720 radials × 400 steps, 2,048 profile samples, 8 sites/composite, indoor grid ≤400 px |
| Config | 13 `AM_*` env vars (data dir, DEM/DSM/basemap URLs, DEM zoom, cache budget, CORS, upload cap, feather, validation threshold, SaaS mode, billing secret) |
| Probes | `/api/health` (liveness) + `/api/ready` (data-dir writable, DEM cache state) |
| Error policy | DEM failures → 502; validation errors → 4xx with actionable text; server logging at startup |
| Audit | centralized middleware → append-only `audit.log` (0600) + tenant-scoped DB, stamped with user id + client IP |
| Tests | 172 test functions / 182 cases (fake DEM world; physics reference values hand-checked incl. anchored ITM/knife-edge/reciprocity invariants; restart & multi-worker simulation; security/tier + consumer-path IDOR + audit regression; planning, two-way, leaky-feeder, auto-placement, compliance, calibration, copilot; API workflows) |

## 7. SaaS & workspace layer

Accounts (PBKDF2, revocable session tokens with 30-day TTL, login lockout),
three roles with tailored dashboards (Command Center / Tactical / Pitch),
project workspaces (save/duplicate/share via capability links), tier
entitlements (basic/pro/enterprise, billing-webhook-gated in SaaS mode),
tenant-scoped audit log, CAPEX/OPEX estimator, branded PDF reports with
white-labeling, async jobs with live progress (4 concurrent cap), and
resource ownership on DXFs and antenna patterns. Full detail:
`SaaS_ARCHITECTURE.md`.

## 8. Known limits (honest boundaries)

The exact engines are proven where a public reference exists: the **NTIA ITM**
(itmlogic port) reproduces the published Crystal Palace validation case to
0.0 dB on all six quantiles (CI-gated ≤ 0.1 dB), and **ITU-R P.1812** runs the
official SG3 reference code with the ITU digital maps; both are exposed in the
UI with their environment parameters (climate zone, N₀, time/location
percentages), **ITU-R P.452-18** (official reference code, clear-air
interference coordination 0.1–50 GHz with worst-case ducting time
percentages) and **ITU-R P.2001** (official wide-range model, 30 MHz–50 GHz,
full 0–100 % time range) are UI-exposed alongside them — with the official
ITU validation examples replayed in CI (worst deviation < 1e-06 dB). The
drive-test calibration loop is closed: a fitted offset/slope correction is
applied directly to subsequent coverage studies. P.1546 remains absent.
Per-pixel clutter comes
from **ESA WorldCover 10 m** (P.1812 representative heights) and uploaded
building footprints / **drone LiDAR** DSMs; a global 3D building database is
still not bundled. Frequency/PCI planning, Erlang B/C, SINR→CQI throughput
maps with saturation verdicts, P.530 availability, per-floor wall maps and the
DAS tree solver are built and UI-exposed — the scheduler model is still
airtime-share, not a per-TTI simulator, and DAQ thresholds remain documented
engineering heuristics, not measured BER curves.

**Field precision is deliberately marked unproven**: the drive-test pipeline
(CSV/GPX ingestion, calibration fit, RMSE CI gates at 8 dB urban / 6 dB rural)
is armed and proven end-to-end on labelled synthetic datasets, but no real
measurement campaign has been ingested yet — the benchmark says so instead of
inventing numbers. The hardware catalog (194 devices, 143 datasheet-grade) is
majority-verified but far from exhaustive. The copilot's deterministic advice
is offline; its optional prose narrator needs an API key (or a local model).
Nominatim place search and first-use WorldCover/DEM tile fetches require
internet.

**On the roadmap, not yet built:** P.1546 and regulator-grade coordination
workflows (P.452-18 interference and P.2001 wide-range are shipped and
validation-anchored);
real drive-test campaigns to close the field-RMSE gates; catalog growth to
500+ via further vendor scrapers; vision-assisted plan/photo reading; agentic
optimization driving site-search/auto-placement toward a coverage-vs-CAPEX
objective.
