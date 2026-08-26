# Changelog

All notable changes to AntennaMaster are recorded here. Versions follow
[semantic versioning](https://semver.org/); the version shown is the app /
Windows-installer version (`dist/AntennaMaster-Setup-<version>.exe`).

## Unreleased

Driven by a deep review: an expert-and-user committee assessed the product
while the running server was probed empirically for behaviour and defects.

### Added
- **Queued coverage studies with live progress.** A full-resolution sweep was
  measured at ~26 s; the planner ran it synchronously behind a static
  "Simulating…" label. Studies now run as background jobs with a real
  percentage and progress bar, reusing job infrastructure that already existed
  but was wired only to the pitch page. Falls back to the synchronous endpoint
  on an older backend.
- **Stop a running simulation.** Cooperative cancellation (checked in the
  sweep's own progress callback), so a run started with the wrong parameters
  no longer has to be waited out while holding a worker slot.
- **Read the signal at any point on the map.** Click a coverage layer to get
  received power, margin, grade and distance/bearing at that spot. The value
  is looked up from the field that painted the raster with identical indexing,
  so the number can never disagree with the colour — pinned by a test that
  samples the PNG and the query together.
- **Browser-level end-to-end tests** (Playwright) covering the real planning
  loop — place a site, run a study, watch progress, read a point — against a
  real backend and a real map, plus sidebar rearrangement surviving a reload.

### Accessibility
- **102 form controls had no accessible name.** Across the planner, indoor
  studio, DXF wizard, auth panel and dashboards, `<label>Text</label>` sat as a
  *sibling* of its input with no `htmlFor` — so screen readers announced those
  controls unnamed (WCAG 1.3.1 / 4.1.2) and clicking a label did not focus its
  field. Every one is now associated via `useId`-derived `htmlFor`/`id` pairs,
  which is purely additive and leaves layout untouched. Found by writing a
  browser test: Playwright's label-based locator could not find the technology
  selector, exactly as a screen reader user could not.

### Fixed
- **NaN in a numeric field returned 500 instead of 422.** Python's JSON parser
  accepts NaN/Infinity but they cannot be serialized back out, so FastAPI's
  default handler raised while rendering the validation error it was echoing.
- **An unreachable elevation source could pin a worker for minutes.** Each
  uncached tile waited out a 30 s timeout serially; a study near the poles
  needs many. A circuit breaker now fails fast for 30 s after three
  consecutive failures, then probes again. Cached areas keep working.
- Backend error text no longer leaks API instructions into the GUI ("retry
  shortly or use POST /api/saas/coverage/async" reached the user's error box).

## 1.1.1

### Fixed
- **Docker deployment was broken.** The compose healthchecks probed the
  host-published ports (8010/3010) from *inside* the containers, where the
  services listen on 8000/3000 — so the backend never became "healthy" and the
  frontend (which waits on `service_healthy`) never started. Pointed both
  healthchecks at the container-internal ports.
- **Cross-tenant DXF read access.** The `/api/dxf/{id}/layers`, `/overlay.png`
  and `/state` endpoints skipped the owner check the mutation endpoints
  enforce, so an authenticated API client could read another account's DXF
  terrain by id. They now go through the shared `resolve_dxf` owner guard.
- Hardened the Live Ops SSE handlers against a malformed frame (unguarded
  `JSON.parse`).

### Changed
- **Coverage palette is now colour-vision-deficiency safe.** Replaced the
  green→yellow→orange→red scale (which relies on the red↔green axis that ~8% of
  men can't distinguish, and had non-monotonic luminance) with ColorBrewer's
  RdYlBu (blue = strong → red = marginal). Still five distinct colours; red =
  weak/no-service stays intuitive. Applies to outdoor and indoor coverage.

### Accessibility
- The drag-and-drop panel arranger is now fully usable without a mouse and on
  touch devices: explicit ▲/▼ move buttons (keyboard/touch/screen-reader
  friendly) alongside drag, an `aria-live` region that announces each move,
  list semantics, and per-panel position labels. Fixed a layout-persistence
  race on first load.

## 1.1.0

### Added
- **Customizable sidebar (drag-and-drop).** An **Arrange panels** mode turns
  every planner sidebar tool into a draggable card: reorder panels by dragging
  the ⠿ handle (or focus it and use ↑ / ↓ — keyboard-accessible, WCAG 2.1.1),
  and hide the tools you never use. The layout (order + hidden set) persists
  per browser and is restored on every visit; **Reset** returns the default.
  Dependency-free native HTML5 drag-and-drop, so it works fully offline.
- **Guided-tour step** introducing the panel arranger, translated EN/FR.

### Changed
- **Coverage study colours.** The single-site and indoor area-coverage rasters
  now use a green → yellow → orange → red **traffic-light scale** (the
  Atoll / Radio-Mobile convention) instead of a single blue hue, so each of the
  five signal-margin levels reads as a distinct colour at a glance. The legend,
  GeoTIFF and KMZ exports pick up the new palette automatically.
- Terrain-validation warnings moved to the top of the sidebar (outside the
  reorderable set) so alerts stay prominent.

### Docs
- USER_GUIDE (EN/FR) and CAPABILITIES document the panel arranger and the
  updated coverage palette.

## 1.0.0

Initial release: terrain engine, DXF pipeline, six propagation models + ITM,
23 technology presets, single-site and multi-site best-server / SINR /
throughput coverage, indoor & underground studios, 3D digital twin, live
telemetry, drone LiDAR, bilingual (EN/FR) UI, Simple Mode, guided tour,
GIS exports (CSV / KML / KMZ / GeoTIFF), SaaS/accounts layer, and a
one-click Windows installer.
