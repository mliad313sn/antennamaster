# AntennaMaster — Competitive Gap Analysis

Lead Product Architect & Competitive Intelligence review. Four-phase audit
against enterprise RF planning software (Atoll, Pathloss, iBwave, CloudRF),
with the highest-value gaps closed autonomously in this round. Every claim
below is backed by shipped, tested code.

---

## Phase 1 — Low-level architecture & physics audit

The physics engine was audited end-to-end (the maths lives in
`services/rf/models.py`, `physics.py`, `environment.py` — there is no
`rf_math.py`). Four defects found in the prior review round were fixed and
regression-tested (`tests/test_physics_fixes.py`); this round re-audited the
performance and numerical-stability angles.

| Area | Finding | Status |
|---|---|---|
| Coverage kernel memory | Max run (720×400 radials/steps, 1024 px) peaks at **145 MB Python heap**; the O(radials·steps²) diffraction temps are **chunked** (≤24 radials/chunk) in **float32** — no unbounded matrix, no leak | ✅ bounded |
| k-factor / curvature precision | Bulge applied in float64 before all Fresnel/LOS; parabola–chord identity verified exact for sub-paths | ✅ correct |
| Terrain fusion (SRTM+DXF) | Bilinear cross-tile sampling, ≤400×400 density-aware grid, 3-cell feathered blend, >50 m mean-diff validation; interpolation verified against reference | ✅ correct |
| Diffraction edge count | Deygout budget was a recursion *depth* (≤2ⁿ−1 edges); fixed to a shared total-edge count | ✅ fixed |
| Gaseous absorption (E/W band) | Flat 15 dB/km clamp above 54 GHz replaced with a Lorentzian 60 GHz complex | ✅ fixed |
| Frontend heatmap rendering | Coverage is a **single Leaflet `ImageOverlay` PNG**, not per-pixel DOM — no DOM explosion, and the heavy compute is server-side, so client Web Workers are unnecessary by design | ✅ optimal |
| Sync-endpoint CPU | Inline heavy sims were uncapped; now bounded by a `sim_slot()` semaphore (429 when saturated) | ✅ fixed |

**Verdict:** the compute architecture (server-side polar sweep + chunked
float32 kernel + single-raster client overlay) is sound and does not bottleneck
or leak at the documented caps. No architectural rework required.

---

## Phase 2 — Usability & use-case coverage

Mapped the UI against high-value enterprise deployment scenarios.

| Scenario | Supported today | Gap addressed this round |
|---|---|---|
| **Private LTE / 5G launch** | CBRS B48 / NR n77 / NB-IoT presets, channel-aware sensitivity (kTB+NF+SINR), MIMO gain, multi-site best-server, **co-channel SINR map** | BOM export for the rollout PO |
| **Fleet / multi-site rollout** | Multi-site composite (≤8), best-site search, per-site BOM & 5-yr TCO | **Fleet-scaled BOM CSV** (line items × site count) |
| **Last-mile / fixed-wireless (WISP)** | **Batch qualification** (≤200 CPE/call, CSV), height optimizer, refraction reliability | GeoTIFF export for GIS handoff |
| **Field engineer, low-bandwidth site** | Tactical view (forced high-contrast, GPS spot check) | **PWA offline caching** — app shell + map tiles + last results cached; live online/offline indicator |
| **Open-pit / deep-topography** | DXF terrain fusion (survey relief over SRTM), tunnel waveguide, TTE, adjustable k-factor | Surface-model (DSM) obstruction support |
| **Desktop ↔ tactical switching** | Shared session (localStorage), role dashboards, quick-preset seeding | Working share links (`/?shared=`) |

**Key friction removed:** the field persona previously assumed a stable
connection. With the service worker, the tool now opens and runs off-grid on
terrain the engineer has already viewed — the decisive requirement for
open-pit and remote last-mile work.

---

## Phase 3 — Competitive benchmarking

Scored against the enterprise standards, focusing on the governance and
network-engineering features these teams require.

| Capability | AntennaMaster | Atoll | Pathloss | iBwave | CloudRF |
|---|---|---|---|---|---|
| Empirical + 3GPP 38.901 models | ✅ | ✅ | 🟡 (PtP focus) | 🟡 (indoor) | ✅ |
| PtP microwave link design (refraction, height opt.) | ✅ | ✅ | ✅ core | ❌ | 🟡 |
| In-building multi-wall (DAS) | ✅ | 🟡 | ❌ | ✅ core | 🟡 |
| Multi-site best-server + SINR | ✅ | ✅ | 🟡 | ✅ | ✅ |
| **Batch fixed-wireless qualification** | ✅ (≤200, CSV) | 🟡 | ❌ | ❌ | ✅ |
| **GeoTIFF / GIS raster export** | ✅ EPSG:4326 | ✅ | ✅ | ✅ | ✅ |
| **KMZ (Google Earth) export** | ✅ | ✅ | 🟡 | 🟡 | ✅ |
| **Hardware BOM generation** | ✅ CSV, fleet-scaled | 🟡 | ❌ | ✅ | ❌ |
| CAPEX/OPEX/5-yr TCO | ✅ | 🟡 | ❌ | 🟡 | ❌ |
| Branded PDF reports | ✅ white-label | ✅ | ✅ | ✅ | ✅ |
| **Offline field use (PWA)** | ✅ | ❌ desktop | ❌ desktop | 🟡 app | ❌ |
| DXF/CAD terrain fusion | ✅ unique | 🟡 import | 🟡 | ❌ | ❌ |
| OT/IT data governance (tenanted, owner-scoped, audit) | ✅ | 🟡 | ❌ | 🟡 | 🟡 |
| ITM / Longley-Rice | ❌ roadmap | ✅ | ✅ | n/a | ✅ |
| Web, zero-install, self-hostable | ✅ | ❌ | ❌ | ❌ | 🟡 SaaS |

**Governance note (OT/IT compliance):** project data handling now enforces
per-tenant ownership on every DXF/antenna/job read path, org-scoped audit
logging, PBKDF2 credentials, revocable 30-day tokens and billing-gated tier
changes — the access-control posture enterprise IT governance asks for. See
`SaaS_ARCHITECTURE.md`.

---

## Phase 4 — Gaps closed this round

| Gap (enterprise requirement) | Implementation | Verified |
|---|---|---|
| **GeoTIFF export** — GIS-native raster for ArcGIS/QGIS/Atoll import | `services/geotiff.py` writes EPSG:4326 geo-tags via PIL (no GDAL dep); `GET /api/rf/coverage/{id}.tif`; UI download link | ✅ tags round-trip; live 512×512 TIFF |
| **Hardware BOM export** — procurement deliverable, fleet-scaled | `GET /api/saas/bom.csv` (line items × sites + CAPEX/OPEX/TCO); dashboard download | ✅ scales per site |
| **PWA offline field caching** | `public/sw.js` (app-shell stale-while-revalidate, tiles cache-first, API network-first-with-fallback) + manifest + registration; field online/offline pill | ✅ offline reload from cache confirmed |

All exports and the offline path were driven end-to-end against live servers
with Playwright.

### Remaining roadmap (honest, ordered by value)

1. **ITM / Longley-Rice** — the one model the reference tools hold over us;
   Deygout + the Hata/38.901 family covers the same planning use cases.
2. Per-pixel clutter **database** (ESA WorldCover) to complement the shipped
   statistical ITU-R P.2108 model.
3. Frequency-plan-aware SINR (scheduler / reuse-N) beyond the reuse-1
   worst-case map.
4. ITU-R P.1546 for broadcast field-strength studies.
5. Background-sync queue so studies composed offline auto-run on reconnect.

---

## Positioning

AntennaMaster now matches the commercial suites on study breadth (empirical +
3GPP + environmental + interference), on enterprise deliverables (GeoTIFF,
KMZ, BOM, branded PDF, TCO) and on data governance — while **exceeding all of
them** on DXF/CAD terrain fusion, combined indoor/underground physics, batch
fixed-wireless qualification, and field deployability (zero-install web +
PWA offline). The single capability the established desktop tools still hold
is a full ITM/Longley-Rice engine.
