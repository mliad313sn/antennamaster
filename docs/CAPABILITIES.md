# AntennaMaster — Complete Functionality, Capability & Capacity Reference

Verified against the codebase: **47 REST endpoints** (27 simulation +
20 SaaS/accounts), **90 backend test functions (100 cases)** + 10 frontend
component tests, 90% backend line coverage. Companion docs: `ASSESSMENT.md`
(benchmark & review history), `SaaS_ARCHITECTURE.md` (accounts, tiers,
workspaces, monetization).

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

## 3. Propagation models (6)

| Model | Range | Use |
|---|---|---|
| Free space (ITU-R P.525) | any | baseline, microwave PtP |
| Okumura-Hata (urban/suburban/open) | 150–1500 MHz | GSM900, PMR, broadcast |
| COST-231 Hata (+metropolitan) | 1500–2000 MHz | GSM1800/DCS |
| 3GPP TR 38.901 RMa LOS/NLOS | 0.5–30 GHz | 4G/5G rural |
| 3GPP TR 38.901 UMa LOS/NLOS | 0.5–100 GHz | 4G/5G urban macro |
| 3GPP TR 38.901 UMi LOS/NLOS | 0.5–100 GHz | small cells, mmWave |

All floor-bounded by FSPL; out-of-validity inputs clamped with API warnings.
**Terrain diffraction on top of any model:** Deygout multi-knife-edge (≤3
edges, ITU-R P.526 loss, k-curved fused profile, grazing-edge recursion
guard); vectorized single-strongest-edge per step in area coverage.

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
  served fraction, margin-classed raster (5 classes, single-hue,
  transparent where unserved). ~2 s for a 10 km 180×100 sweep (cached DEM).
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

**Exports:** profile CSV, coverage PNG + KMZ (Google Earth GroundOverlay),
indoor heatmap PNG.

## 6. Operations & scale

| Aspect | Capacity / behavior |
|---|---|
| Multi-worker safety | rasters + DXF state disk-backed; any worker serves any result; restart-safe (tested) |
| Result retention | last 200 raster results on disk (auto-pruned) |
| Upload caps | DXF ≤100 MB (`AM_MAX_DXF_MB`), antenna files ≤2 MB |
| Simulation caps | radius ≤150 km, 720 radials × 400 steps, 2,048 profile samples, 8 sites/composite, indoor grid ≤400 px |
| Config | 12 `AM_*` env vars (data dir, DEM/DSM URLs, DEM zoom, cache budget, CORS, upload cap, feather, validation threshold, SaaS mode, billing secret) |
| Probes | `/api/health` (liveness) + `/api/ready` (data-dir writable, DEM cache state) |
| Error policy | DEM failures → 502; validation errors → 4xx with actionable text; server logging at startup |
| Tests | 113 test functions / 123 cases (fake DEM world; physics reference values hand-checked; restart & multi-worker simulation; security/tier + consumer-path IDOR regression; planning tools; API workflows) |

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

Median empirical models + knife-edge diffraction (no ITM/P.1546/P.452 —
Deygout + the Hata/38.901 family covers the same planning use cases);
clutter is statistical (ITU-R P.2108), not a per-pixel land-use database;
SINR assumes worst-case co-channel reuse-1 (no frequency planning /
scheduler model); multi-floor is a penetration term, not per-floor wall
maps; building obstruction requires a user-supplied DSM source
(`AM_DSM_URL` — no public global Terrarium DSM exists); Nominatim search
requires internet.
