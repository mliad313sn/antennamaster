# AntennaMaster — Low-Level Assessment & Competitive Benchmark

Date: 2026-07 · Scope: full application audit (backend + frontend), feature
benchmark against the mainstream RF planning tools, and the gap-closure plan
implemented in this iteration.

## 1. Low-level assessment (v1 → v2)

### v1 state (after the initial Terrain & Georeferencing module)

| Area | v1 status | Verdict |
|---|---|---|
| Base terrain | Terrarium 30 m tiles, Z/X/Y disk cache, bilinear cross-tile sampling | solid |
| Local terrain | DXF parse (6 entity families), 3 georef modes, gridding, feathered fusion, validation | solid, a differentiator |
| Physics | k=4/3 curvature, single knife-edge, Fresnel-1 clearance | **minimal** — one implicit "model" |
| Path-loss models | none (LOS geometry only) | **critical gap** |
| Technology studies | none — user enters a bare frequency | **critical gap** |
| Coverage maps | none — point-to-point profile only | **critical gap** (the defining feature of every competitor) |
| Link budget | none (no powers/gains/sensitivity) | **critical gap** |
| Antennas | none (isotropic implied) | gap |
| Map providers | hardcoded OSM | gap |
| Multi-edge diffraction | single edge only | gap (mountains under-estimated) |

### v2 — what this iteration adds

* **Propagation model library** (`app/services/rf/models.py`): FSPL (ITU-R
  P.525), Okumura-Hata 150–1500 MHz, COST-231 Hata 1500–2000 MHz, and the
  three 3GPP TR 38.901 macro/micro models (RMa, UMa, UMi LOS/NLOS) valid to
  100 GHz — every model floor-bounded by free space, with out-of-range
  warnings instead of hard failures. Terrain-aware **Deygout multi-edge
  diffraction** (up to 3 edges, computed on the k=4/3 curved fused profile)
  is added on top of any empirical model.
* **Technology presets** (`rf/technologies.py`): GSM 900/1800 (2G),
  UMTS 900/2100 (3G), LTE 800/1800/2600 (4G), 5G NR n28/n78/n257 mmWave,
  TETRA, PMR446, FM & DVB-T broadcast, Wi-Fi 2.4/5.8, LoRaWAN, 18 GHz PtP
  backhaul, plus a fully-custom study. Each preset carries typical EIRP
  components, receiver sensitivity, antenna heights and its best-suited
  model; every field is overridable per request.
* **Area coverage engine** (`terrain/coverage.py`): polar sweep (radials ×
  steps) over the fused terrain — the Radio Mobile / SPLAT! architecture —
  with per-step strongest-edge diffraction (vectorized (S×S) per ray),
  optional 3GPP parabolic sector antenna pattern, margin-classed RGBA raster
  (single-hue sequential ramp), legend and served-area statistics.
* **Link-budget studies on profiles**: `/api/terrain/profile` accepts a
  technology + overrides and returns per-sample RX power, path loss,
  Deygout loss, margin and served/unserved verdict.
* **Map-provider compatibility**: Leaflet layer switcher with OSM,
  OpenTopoMap, Carto Light/Dark, Esri Imagery/Topo, plus a custom XYZ
  template slot — any standard tile provider works.

## 2. Benchmark vs. mainstream tools

Legend: ✅ has it · 🟡 partial · ❌ missing

| Capability | **AntennaMaster v2** | SPLAT! | Radio Mobile | CloudRF | Atoll / HTZ (commercial) |
|---|---|---|---|---|---|
| Global DEM w/ auto-download + cache | ✅ Terrarium 30 m | 🟡 manual SRTM files | 🟡 manual SRTM | ✅ | ✅ multi-source |
| **Private/site CAD (DXF) terrain fusion** | ✅ unique: feathered patch + validation | ❌ | ❌ | ❌ | 🟡 via import tooling |
| Point-to-point profile + Fresnel | ✅ | ✅ | ✅ | ✅ | ✅ |
| Earth curvature k-factor | ✅ (adjustable) | ✅ | ✅ | ✅ | ✅ |
| Diffraction | ✅ Deygout ≤3 edges | ✅ ITM | 🟡 | ✅ multiple | ✅ many |
| Area coverage raster | ✅ polar sweep | ✅ | ✅ | ✅ | ✅ |
| Empirical models (Hata family) | ✅ | ❌ (ITM only) | 🟡 | ✅ | ✅ |
| 3GPP TR 38.901 (4G/5G, mmWave) | ✅ | ❌ | ❌ | 🟡 | ✅ |
| Longley-Rice / ITM | ❌ (roadmap) | ✅ | ✅ | ✅ | ✅ |
| ITU-R P.1546 / P.452 / P.526 full | 🟡 P.526 single/multi edge | 🟡 | 🟡 | ✅ | ✅ |
| Technology presets (2G→5G, IoT, broadcast…) | ✅ 23 presets | ❌ | 🟡 | ✅ | ✅ |
| Link budget w/ sensitivity & margin | ✅ | 🟡 | ✅ | ✅ | ✅ |
| Sector antenna patterns | ✅ parametric | 🟡 | ✅ files | ✅ | ✅ (MSI/planet) |
| Antenna pattern file import (MSI/ANT) | ✅ | 🟡 | ✅ | ✅ | ✅ |
| Multi-site / best-server analysis | ✅ | 🟡 | ✅ | ✅ | ✅ |
| **Co-channel SINR / interference map** | ✅ reuse-1 S/(I+N) | ❌ | 🟡 | ✅ | ✅ |
| Clutter / land-use loss | ✅ ITU-R P.2108 (statistical) | ❌ | 🟡 | ✅ (database) | ✅ (database) |
| **Batch receiver qualification (fixed-wireless)** | ✅ 200/call, CSV | ❌ | 🟡 manual | ✅ | 🟡 |
| **Antenna height optimizer** | ✅ LOS + 60% F1 | ❌ | ❌ | 🟡 | ✅ |
| **Dual-k refraction reliability** | ✅ k=4/3 & 2/3 | 🟡 | 🟡 | ✅ | ✅ |
| **Best-site candidate search** | ✅ grid ranking | ❌ | ❌ | 🟡 | ✅ |
| Building obstruction (DSM) | ✅ optional `AM_DSM_URL` | ❌ | ❌ | 🟡 | ✅ |
| Web UI, no install | ✅ | ❌ CLI | ❌ Windows | ✅ SaaS | ❌ desktop |
| Map provider choice / custom XYZ | ✅ 6 + custom | ❌ | 🟡 | 🟡 | ✅ |
| Open source / self-hosted | ✅ | ✅ | 🟡 freeware | ❌ | ❌ |

**Positioning**: v2 matches the open tools (SPLAT!/Radio Mobile) on their
core coverage/profile features while exceeding all of them on CAD-terrain
fusion and modern 3GPP models, in a self-hosted web app. Remaining distance
to commercial suites (Atoll/HTZ) is in multi-site network planning, measured
antenna pattern files, clutter data and ITM/P.1546 — tracked below.

## 3. Deep use-case audit → indoor & underground extension (v3)

A per-use-case walk of who runs coverage studies and whether v2 could serve
them exposed a structural blind spot: **every v2 study assumed outdoor,
above-ground, DEM-visible geometry.** Concretely:

| Use case | Actor | v2 status | v3 |
|---|---|---|---|
| Macro cell planning (2G→5G) | MNO RF planner | ✅ | ✅ |
| Rural broadband / WISP PtMP | WISP | ✅ | ✅ |
| Broadcast (FM/DVB-T) | broadcaster | ✅ | ✅ |
| PMR / event radio | integrator | ✅ | ✅ |
| Microwave backhaul | transmission eng. | ✅ | ✅ |
| **In-building Wi-Fi / DAS** | IT / neutral host | ❌ no walls, no materials | ✅ DXF multi-wall engine |
| **Metro station / basement coverage** | transit operator | ❌ | ✅ floor-plan engine (underground = concrete/soil materials) |
| **Road/rail tunnel radio** (TETRA, FM rebroadcast, 5G) | tunnel operator | ❌ DEM sees the mountain, not the bore | ✅ Emslie waveguide model |
| **Mine communications** (UHF leaky-feeder planning, gallery links) | mine operator | ❌ | ✅ tunnel model + rock/pillar materials |
| **Cave rescue / mine emergency TTE** | rescue services | ❌ | ✅ VLF through-earth link (skin depth + 1/r³ induction) |

v3 additions closing this:

* **DXF reinterpreted as structure**: the same uploaded DXF can now be read
  as walls/galleries (LINE, LWPOLYLINE, POLYLINE, ARC/CIRCLE → 2D segments,
  per-layer material assignment with name-based defaults) instead of relief.
* **Material library** (12 materials, dB per crossing at 900/2400/5800 MHz,
  log-f interpolated): drywall→metal, plus rock/soil for underground.
* **COST-231 multi-wall engine**: vectorized ray/segment crossing count per
  grid cell, FSPL(3D) + Σ wall losses → margin-classed heatmap in drawing
  coordinates (no georeferencing required), walls composited for context.
* **ITU-R P.1238** site-general indoor model (power law + floor penetration)
  for quick no-plan studies.
* **Tunnel waveguide (Emslie/Lagace)**: dominant-mode dB/m from cross-section,
  wall permittivity, roughness and tilt; two-mechanism profile
  (direct ray vs guided mode) with breakpoint; reproduces the defining
  physics that higher frequencies travel *farther* underground.
* **Through-the-earth**: skin-depth attenuation + near-field 1/r³ spreading,
  ground-conductivity presets — the VLF mine-paging use case.

## 4. Multi-persona review panel → ergonomy / agility / scalability (v4)

Four independent reviewers examined the full codebase, each from a different
métier: a **senior RF planning engineer** (operator, Atoll/Planet user), a
**field technician / WISP installer** (laptop/phone on site), a
**backend/platform architect** (production self-hosting), and a **UX designer
+ broadcast/DAS engineer** (heuristic evaluation + "other métiers"). Their
findings converged strongly; the table shows each finding and its status.

### Ergonomy

| Finding (personas) | Status |
|---|---|
| TX/RX placement click-only; no exact coordinate entry (all 4) | ✅ editable lat/lon inputs, paste-friendly |
| Page refresh wipes the whole session (3) | ✅ localStorage persistence incl. DXF rebinding via new `GET /api/dxf/{id}/state` |
| No place/coordinate search; map fixed on Austria (2) | ✅ header search: "lat, lon" jump + Nominatim geocoding; last map view remembered |
| No device GPS use (field tech) | ✅ "Use my GPS position" button |
| No swap-TX/RX quick action (field tech) | ✅ ⇄ swap button (coords + heights) |
| No exports — nothing to hand a client (planner, UX) | ✅ profile CSV endpoint + download link, coverage PNG + **KMZ (Google Earth)**, indoor heatmap PNG |
| Un-debounced refetch on every keystroke (2) | ✅ 350 ms debounce |
| Number inputs snap to fallback when cleared (2) | ✅ string-state fields parsed at fetch time |
| Data computed but never shown: worst obstruction, coverage TX-ground/peak-power, indoor min/max dBm, TTE total loss (UX) | ✅ all surfaced; worst obstruction marked on the chart |
| Custom tile provider dead code (2) | ✅ sidebar input, persisted, feeds the layer switcher |
| No responsive layout (2) | ✅ ≤800 px stacks sidebar/map/chart |
| Modals lack Escape/aria (UX) | ✅ Escape-to-close + aria-labels on both modals |
| Dark mode (UX) | ✅ full dark token set, OS-following with header toggle |

### Agility

| Finding | Status |
|---|---|
| Coverage UI hid link-budget overrides the API accepts (planner) | ✅ "Site link budget" panel: power/gains/losses/sensitivity |
| No antenna downtilt / vertical pattern (planner) | ✅ parametric vertical pattern + mechanical downtilt in the engine and UI |
| Median-only prediction; no shadow-fade margin (planner) | ✅ `shadow_margin_db` in engine + "Fade margin" field (5.5 dB≈90%, 8 dB≈95% hints) |
| k-factor locked to 4/3 for coverage (planner) | ✅ `k_factor` on the coverage API |
| Presets hardcoded in Python (planner) | ✅ operator overrides merged from `DATA_DIR/technologies.json` |
| All config hardcoded (architect) | ✅ `AM_*` env vars: data dir, DEM URL/zoom, CORS, upload cap, thresholds |

### Scalability

| Finding | Status |
|---|---|
| Coverage/indoor PNGs in per-process dicts → 404 across workers/restarts (architect, planner) | ✅ disk-backed `results_store` (any worker serves any result; pruned by count) |
| DXF georef state memory-only → 409 on sibling worker (architect) | ✅ JSON sidecar + deterministic rebuild (`ensure_ready()`), tested via simulated restart |
| Unbounded decoded-tile RAM cache (architect) | ✅ LRU capped at 2000 tiles (~500 MB) |
| Per-point Python loop in tile sampling (architect, planner) | ✅ fully vectorized web-mercator projection |
| Per-step `_ke_loss` list comprehension (planner) | ✅ vectorized `ke_loss_array` |
| Served-area KPI polar-biased optimistic (planner) | ✅ area-weighted by radius |
| No readiness probe; liveness only (architect) | ✅ `/api/ready` (data-dir writable + DEM cache state) |
| No logging config (architect) | ✅ basicConfig at startup (route-level tracebacks land in server logs) |
| On-disk DEM cache unbounded (architect) | ✅ mtime-LRU eviction to AM_DEM_CACHE_MB budget (default 2 GB), swept every 100 downloads |
| Heavy sims block the threadpool under many concurrent users (architect) | ⏳ roadmap (background job queue) |

## 5. Deep review round (v7): physics audit, authz hardening, planning tools

Three independent expert reviews (RF/numerics, backend security, frontend/UX)
drove this round. Every finding was verified before fixing.

**Physics defects fixed (numerically confirmed):**
- Gaseous attenuation clamped all f ≥ 54 GHz to the 60 GHz peak (~15 dB/km),
  making E/W-band (71–94 GHz) links uncoverable; replaced with a Lorentzian
  oxygen-complex model that decays to ~0.8 dB/km through those windows.
- `fresnel_clearance_ratio` was taken at min-absolute-clearance, not
  min(clearance/F1) — could pass the 60%-F1 rule on an obstructed path.
- Deygout `max_edges` was a recursion depth (summed up to 2ⁿ−1 edges,
  +6 dB in rugged terrain); now a shared total-edge budget.
- Measured MSI patterns double-counted electrical downtilt.

**Security (cross-tenant IDOR / tier-bypass class):** the DXF/antenna/job
*read* paths were built without threading `user` through, so ownership and
tier checks that existed on the *mutation* paths never applied to the
*consumers*. Closed with a central `resolve_dxf()` guard on every DXF
consumer, owner-scoped `load_antenna()`, owner-scoped async jobs, and a
concurrency cap (`sim_slot()`) on the synchronous heavy endpoints.

**New value features:**
- Batch receiver qualification (`POST /api/rf/batch`, JSON/CSV, ≤200/call) —
  the fixed-wireless/WISP workflow, with a paste-a-list UI + CSV export.
- Antenna height optimizer (`GET /api/terrain/optimize-heights`) — minimum
  TX/RX heights for LOS and 60% first-Fresnel by bisection.
- Dual-k refraction reliability on every profile (`rf.refraction`).
- Best-site candidate search (`POST /api/rf/site-search`).
- Frontend: session now persists the environmental knobs; share links
  actually open (`/?shared=<token>`); stale-coverage auto-clear; coordinate
  entry no longer drops pins at longitude 0.

## 6. Roadmap (not yet implemented, ordered by value)

1. **ITM / Longley-Rice** propagation option (parity with SPLAT!/RM verdicts).
2. ITU-R P.1546 for broadcast studies.
3. Per-pixel clutter *database* (ESA WorldCover) to complement the
   statistical P.2108 model now shipped.
4. Indoor/outdoor penetration-loss presets (O2I from TR 38.901).
5. Leaky-feeder cable modeling for tunnels (longitudinal loss + coupling).
6. Georeferencing of floor plans onto the map so indoor heatmaps overlay the
   outdoor coverage.
7. Frequency-plan-aware SINR (scheduler / reuse-N) beyond the reuse-1
   worst-case map now shipped.

Done in v7: ~~clutter loss~~ (P.2108), ~~multi-floor indoor~~, ~~SINR /
interference~~, ~~rain fade for PtP~~, ~~building obstruction~~ (DSM).
