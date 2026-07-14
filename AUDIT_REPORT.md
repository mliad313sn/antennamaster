# AUDIT_REPORT — RF Systems Architecture & QA Cycle

Role: Senior RF Systems Architect & Principal QA Engineer.
Scope: 4-phase deterministic audit → implementation cycle over the full stack
(25 endpoints, 6 propagation + 4 confined-space models, Next.js frontend).

## Phase 1 — Capability & limits audit (measured, not estimated)

| Path | Measured | Verdict | Action taken |
|---|---|---|---|
| Coverage engine @ max res (720×400 radials/steps, 50 km) | 4.7 s CPU (cached DEM) | acceptable at ceiling; default 180×100 ≈ 0.2 s | none needed; caps already enforced by Pydantic |
| Per-sample Deygout loop @ 2,048 samples | 0.31 s | NOT the feared O(n²) blow-up (early exit on clear sub-paths) | none needed |
| Profile JSON payload @ 2,048 samples | 330 KB raw | too heavy for field links | ✅ **GZip middleware** (≥8 KB responses, ~8× reduction) |
| Recharts SVG @ 2,048 points | jank risk (2k+ DOM nodes × 4 series) | real | ✅ **peak-preserving downsampler** (≤512 rendered points; buckets keep their highest terrain sample so RF-deciding peaks survive) |
| Coverage raster | fixed 512 px (~600 m/px @150 km) | blocky for reports | ✅ `raster_px` request param (128–1024) |
| Leaflet heatmap grid limit | N/A by design | — | coverage ships as **pre-rendered PNG overlays**, not client-side heatmap grids, so there is no browser matrix limit to hit |
| numpy/scipy memory | (S,S) per-radial broadcast = 1.3 MB @400 steps, sequential per radial; grids ≤400×400 | bounded | documented; tile RAM cache already LRU-capped |

## Phase 2 — Telecom deployment-matrix integration

1. **Private LTE & 5G** — ✅ new presets `private_lte_b48` (CBRS 3.6 GHz),
   `private_nr_n77` (100 MHz), `private_lte_iot` (NB-IoT/LTE-M 1.4 MHz) with
   explicit **channel width, noise figure, target SINR and MIMO gain**;
   receiver sensitivity now derives from first principles
   (kTB + 10log₁₀BW + NF + SINR) so bandwidth changes rescale the budget
   (verified: 10× BW = exactly +10 dB; NB-IoT beats a 100 MHz carrier by
   >15 dB). MIMO diversity gain enters both profile and coverage budgets.
2. **Rugged/industrial terrain** — ✅ deep-pit topography verified by test:
   an RX on the floor of a 150 m sheer-walled pit sees >15 dB rim
   diffraction while the same-distance flat path sees <2 dB (the Deygout
   engine handles sharp elevation drops natively — the audit *proved* it
   rather than assuming it). ✅ **foliage/clutter model** (Weissberger MED,
   0.23–95 GHz, 400 m validity clamp — the P.833-class vegetation knob)
   applied per-study and across coverage areas ("dense last-mile clutter").
3. **PtP/PtMP backhaul** — ✅ **rain attenuation** (ITU-R P.838-3 k·Rᵅ
   coefficients, log-interpolated 1–100 GHz, P.530 effective-path-length
   reduction) and ✅ **atmospheric gaseous absorption** (P.676-style dry-air
   + water-vapour fits, 22 GHz and 60 GHz lines) — both in the profile
   study breakdown and the coverage engine. Reference values verified
   (20 GHz @ 25 mm/h ≈ 2.75 dB/km).
4. **Field engineer tools** — already present from prior cycles, re-verified:
   profile CSV export, coverage KMZ/PNG, responsive ≤800 px layout, GPS
   placement, typed coordinates, session persistence.

## Phase 3 — Gap execution & UI presets

- All Phase 1/2 gaps implemented (this document is the gap ledger; every
  row above marked ✅ landed in this cycle, with tests).
- UI quick presets: the technology dropdown now includes the **Private**
  group (Private LTE B48/CBRS, Private 5G n77, NB-IoT) and **VHF land
  mobile 150 MHz** alongside the existing Microwave PtP 18 GHz preset —
  one click loads frequency, model, powers, channel width and MIMO.
- Study panel exposes foliage depth + rain rate; the link-budget readout
  itemizes foliage / rain / gas losses, MIMO gain and derived sensitivity.

## Phase 4 — Stress test & refinement

- 50 km coverage over fused DXF+SRTM terrain executed end-to-end (see test
  run + live verification); 720×400 ceiling case: 4.7 s.
- UI freeze protection: coverage is a PNG overlay (no per-cell DOM);
  profile chart hard-capped at 512 rendered points with peak retention;
  profile fetches debounced 350 ms with stale-response cancellation.
- OpenAPI: tag metadata + endpoint docstrings; interactive docs at `/docs`.
- Frontend: strict TypeScript, all API DTOs typed in `lib/types.ts`,
  production build clean.
- Test suite: **60 tests** (physics reference values hand-computed,
  restart/multi-worker simulations, deep-pit and foliage/rain behavior).

## Residual known limits (deliberate, documented)

Longley-Rice/ITM and P.1546 not implemented (roadmap #1); clutter is a
global depth knob, not per-pixel land-use rasters; rain applies uniformly
(no cell-by-cell weather); no SINR/interference between sites; heavy sims
run in the request thread-pool (bounded by resolution caps — a job queue is
the next scaling step past ~10 concurrent heavy users).
