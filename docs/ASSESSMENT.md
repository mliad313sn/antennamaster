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
| Technology presets (2G→5G, IoT, broadcast…) | ✅ 17 presets | ❌ | 🟡 | ✅ | ✅ |
| Link budget w/ sensitivity & margin | ✅ | 🟡 | ✅ | ✅ | ✅ |
| Sector antenna patterns | ✅ parametric | 🟡 | ✅ files | ✅ | ✅ (MSI/planet) |
| Antenna pattern file import (MSI/ANT) | ❌ (roadmap) | 🟡 | ✅ | ✅ | ✅ |
| Multi-site / best-server analysis | ❌ (roadmap) | 🟡 | ✅ | ✅ | ✅ |
| Clutter / land-use layers | ❌ (roadmap) | ❌ | 🟡 | ✅ | ✅ |
| Web UI, no install | ✅ | ❌ CLI | ❌ Windows | ✅ SaaS | ❌ desktop |
| Map provider choice / custom XYZ | ✅ 6 + custom | ❌ | 🟡 | 🟡 | ✅ |
| Open source / self-hosted | ✅ | ✅ | 🟡 freeware | ❌ | ❌ |

**Positioning**: v2 matches the open tools (SPLAT!/Radio Mobile) on their
core coverage/profile features while exceeding all of them on CAD-terrain
fusion and modern 3GPP models, in a self-hosted web app. Remaining distance
to commercial suites (Atoll/HTZ) is in multi-site network planning, measured
antenna pattern files, clutter data and ITM/P.1546 — tracked below.

## 3. Roadmap (not yet implemented, ordered by value)

1. **ITM / Longley-Rice** propagation option (parity with SPLAT!/RM verdicts).
2. **Antenna pattern file import** (MSI Planet / .ant) replacing the
   parametric sector when available.
3. **Multi-site coverage** with best-server / SINR composite rasters.
4. **Clutter** (ESA WorldCover) as a per-pixel additional loss table.
5. ITU-R P.1546 for broadcast studies; P.530 rain fade for PtP microwave.
6. Indoor/outdoor penetration-loss presets (O2I from TR 38.901).
