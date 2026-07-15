# VISION_ARCHITECTURE — 3D Digital Twin, Live Telemetry & LiDAR

AntennaMaster's transition from a 2D calculator to an immersive, live 3D digital
twin. Three layers, each built on the platform's existing physics so the "wow"
is grounded in the same math the planner already trusts.

```
 ┌─────────────────────── Frontend (Next.js) ───────────────────────┐
 │  2D Leaflet map  ⇄  3D CesiumJS globe (Globe3D)                   │
 │  Live Operations dashboard (/live)   LiDAR panel                  │
 └──────────────┬───────────────────────────┬───────────────────────┘
                │ heightmap.bin / basemap    │ SSE / WS / REST
 ┌──────────────▼───────────────────────────▼───────────────────────┐
 │                        FastAPI backend                            │
 │  terrain.heightmap  telemetry(ENGINE)  lidar(DSM)                 │
 │        └── fused SRTM+DXF ── same engine ── Deygout diffraction   │
 └───────────────────────────────────────────────────────────────────┘
```

---

## Phase 1 — 3D volumetric rendering (CesiumJS)

The 3D globe renders from the platform's **own** fused SRTM+DXF terrain — no
Cesium Ion key, works offline. Cesium's prebuilt global is loaded at runtime
from `/cesium` (staged by `scripts/copy-cesium.mjs`), so it never bloats the
Next bundle, and heightmap decoding runs in Cesium's own Web Workers so the UI
thread never blocks.

**Component:** `frontend/components/Globe3D.tsx` (a seamless 2D/3D toggle on the
map). Renders TX/RX masts, a glowing LOS, a semi-transparent **3D Fresnel
cylinder** following the true line of sight, **red terrain-intrusion markers**
where the fused relief rises into the Fresnel zone (using each profile sample's
`fresnel_lower` edge), and the coverage heatmap **draped over the 3D terrain**.

### Endpoint

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/terrain/heightmap/{level}/{x}/{y}.bin` | int16 heightmap tile (metres, row-major N→S) for Cesium's `CustomHeightmapTerrainProvider`, sampled from the fused model. `?size=` (17–129), `?dxf_id=`, `?surface=`. Levels below 8 return a flat tile (level-of-detail floor) so a coarse view never fetches the whole hemisphere's DEM. |

Service: `backend/app/services/terrain/heightmap.py` (`tile_rectangle`,
`heightmap_int16`). Cesium `GeographicTilingScheme` geometry: 2 root tiles in X,
1 in Y.

---

## Phase 2 — Live telemetry & digital-twin engine

Ingests real-time asset positions (fleet-management systems, IoT trackers) and
correlates each against the platform's RF coverage prediction — the bridge from
planning to live operations.

**Correlations**

* **Dead-zone entry** — an asset moving into a predicted no-coverage area
  (evaluated against the configured TX + technology via the same link budget the
  planner uses) is flagged so the UI flashes it yellow.
* **RF-disconnect correlation** — when an asset stops transmitting, the event is
  logged *with* whether its last position was inside a predicted dead zone:
  "we lost the tracker exactly where the RF model said we would".

**Engine:** `backend/app/services/telemetry.py` — thread-safe `TelemetryEngine`
(`ENGINE` singleton). Core (`ingest` / `sweep` / `snapshot`) is synchronous and
framework-agnostic: the coverage predicate is injected and staleness is judged
against a caller-supplied monotonic `now`, so it is deterministic under test. A
lifespan-managed background sweeper flags disconnects every 5 s (30 s timeout).

**Dashboard:** `frontend/app/live/page.tsx` + `components/LiveOps.tsx` — Leaflet
map with SSE-driven moving assets (polling fallback), green / yellow-pulsing /
grey RF status, a correlation event log, a coverage-context binder, and a demo
feeder that walks an asset out of coverage.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/telemetry/coverage-context` | Bind the twin to an RF prediction (TX + technology) for dead-zone correlation. |
| POST | `/api/telemetry/ingest` | Ingest one or more position pings (FMS/IoT feed). |
| WS | `/api/telemetry/ws` | WebSocket ingest for high-rate feeds; echoes the updated asset. |
| GET | `/api/telemetry/stream` | **Server-Sent Events** stream of the live twin (periodic state + correlation events). |
| GET | `/api/telemetry/state` | Current snapshot (assets + coverage context + event cursor). |
| GET | `/api/telemetry/events?since=` | Correlation events after a cursor (dead-zone entries, RF disconnects). |

Event types: `asset_online`, `enter_dead_zone`, `exit_dead_zone`,
`rf_disconnect` (carries `in_dead_zone` + `correlation`), `asset_reconnect`.

---

## Phase 3 — Drone LiDAR / point-cloud ingestion

A drone LiDAR survey captures the real 3D world — building roofs, tree canopy,
stockpiles, parked haul trucks. Feeding it in replaces the *statistical* clutter
model (ITU-R P.2108) with **actual physical obstructions** the diffraction math
bends over.

**Pipeline:** `backend/app/services/lidar/pointcloud.py` parses `.las`/`.laz`
(laspy + lazrs), rasterises the points into a **Digital Surface Model** (maximum
return per cell — the top of whatever the beam hits), and packages it as the
same `DxfTerrainGrid` + `KnownCrsTransform` interface the fusion engine already
consumes. A profile/coverage run over the DSM footprint therefore computes
**Deygout diffraction against the surveyed surface**, feathered back onto the
SRTM base outside the flown area. A bare-earth DTM (ground class / min return)
gives per-object heights (building = DSM − DTM).

**Frontend:** `components/LidarPanel.tsx` — upload a cloud, see DSM stats, run a
surveyed-surface-vs-bare-terrain diffraction comparison over the placed TX/RX.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/lidar/upload` | Ingest a `.las`/`.laz` cloud → DSM overlay. Form: `file`, `epsg?` (read from the file when embedded), `cell_m?`. Returns `dsm_id`, point count, CRS, surface/object-height stats, lon/lat bounds. |
| GET | `/api/lidar/{dsm_id}/info` | DSM statistics + footprint. |
| GET | `/api/lidar/{dsm_id}/profile` | Profile whose diffraction is computed against the surveyed surface, with a bare-terrain comparison and per-sample obstruction height. |

**Validated live:** a 50 m building on real 895 m terrain raised the modelled
diffraction loss from **40.3 dB (bare) to 114.2 dB (surveyed surface)** and
blocked line of sight — the physics now sees the building.

---

## Optimisation notes

* Cesium loads at runtime from staged static assets, not the Next bundle (the
  main page's First Load JS is unchanged); terrain decoding runs in Cesium's Web
  Workers.
* Heightmap tiles carry a level-of-detail floor so coarse views are cheap.
* The telemetry engine is in-memory and lock-guarded; the dashboard degrades
  from SSE to polling automatically.
* DSM rasters are capped (`MAX_GRID_CELLS`) so a dense survey cannot allocate an
  unbounded grid.

## Tests

Backend: `test_heightmap.py` (6), `test_telemetry.py` (8), `test_lidar.py` (5)
— terrain tiles, dead-zone/disconnect correlation, LAS parsing + DSM diffraction
against a synthetic building. Frontend: type-checked and production-built with
the Cesium, Live Ops and LiDAR surfaces; Cesium/WebGL mount verified headless.
```
