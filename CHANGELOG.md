# Changelog

All notable changes to AntennaMaster are recorded here. Versions follow
[semantic versioning](https://semver.org/); the version shown is the app /
Windows-installer version (`dist/AntennaMaster-Setup-<version>.exe`).

## Unreleased

Driven by a deep review: an expert-and-user committee assessed the product
while the running server was probed empirically for behaviour and defects.

### Fixed — French was advertised but not delivered

- **Four of the five routes shipped in English only.** `DashNav` offers every
  user an EN/FR switch, and the locale files were at full parity — but
  `/field`, `/dashboard`, `/pitch`, `AuthPanel`, `MapView` and `ProfileChart`
  contained *zero* `t()` calls between them, so a French field technician who
  switched language still got an English product on their own page. (The
  committee reported the strings as "already there and simply unwired"; in
  fact no `auth`/`field`/`dashboard`/`pitch` section existed in *either*
  language, so they had to be written.) `AuthPanel` — the gate to every
  account — `/field`, `/dashboard`, `/pitch`, the Leaflet map (placement hint
  and the click-to-inspect signal popup) and the terrain chart (series names,
  axis labels, tooltip) are now all translated: **616 keys in each language**,
  up from 521, with guards keeping the two locales key-for-key identical, free
  of empty strings, and consistent in their `{{interpolation}}` tokens.
- **Plan cards could not be chosen by keyboard.** The registration tier picker
  was a bare `<div onClick>`: not focusable, not announced, unusable without a
  pointer. It is now a proper `radiogroup` with `aria-checked` and Enter/Space.

### Added — coverage as data, not just as a picture

- **`GET /api/rf/coverage/{id}.tif?band=rx_power|margin`** returns a
  **single-band Float32 GeoTIFF** in EPSG:4326 with `NaN` beyond the study
  radius, declared as the nodata value. Until now every GIS export was an
  8-bit RGBA image of five hard-coded margin classes with alpha baked in — a
  cartographic artifact, not a dataset: a GIS team could not threshold it at
  their own −95 dBm, reclassify it, or intersect it with a demand layer. The
  numeric field was already computed and persisted as a sidecar and simply
  never exported. It is resampled with exactly the geometry and
  nearest-neighbour indexing that painted the picture, so the two line up
  pixel-for-pixel and can never disagree. Verified by opening the output with
  rasterio: 1 band, `float32`, `EPSG:4326`, `nodata=nan`, values round-tripped
  exactly. Without `band` the export is unchanged, so existing links keep
  working; an unknown band is refused with 422 rather than ignored.
- **Fixed a GDAL warning on every export.** `GeoASCIIParams` carried an
  explicit `\x00` on top of the terminator the TIFF writer adds, so every GIS
  tool opening an AntennaMaster GeoTIFF logged *"contains null byte … value
  incorrectly truncated"*. Both exports now write the string the spec asks for.

### Fixed — the planner on a phone

- **Three nested scrollers, none of them reachable.** The desktop shell pins
  `.app-shell` to the viewport and gives *both* `.app-main` and `.sidebar`
  their own `overflow`, the sidebar additionally with
  `overscroll-behavior: contain`. Stacked at 390×844 that produced ~1 480 px of
  content in a ~727 px box whose scroll no gesture could reach: the sidebar
  swallowed the touch instead of chaining to its parent, and Leaflet consumed
  every touch over the map — so the elevation profile sat below the fold with
  no way to get to it. Below 800 px the document itself now scrolls (measured:
  `scrollHeight 1484 / clientHeight 727`, every `overflow` back to `visible`),
  and the map takes a bounded height instead of claiming the viewport.
- **Touch targets.** Sidebar controls are ≥ 44 px on small screens — the field
  view already did this and the planner never inherited it.
- **A `Pixel 5` Playwright project is now part of the e2e gate**, asserting no
  horizontal scroll, that the page below the fold is reachable, that the
  sidebar no longer traps the scroll, the 44 px targets, and that the 2D/3D
  toggle is genuinely on top and responds to a click.

### Fixed — accessibility (screen reader and keyboard)

- **Nothing was ever announced.** The entire frontend contained one live
  region, so a coverage sweep ran for up to half a minute in complete silence
  and every failure appeared in an inert `<div>`. A study now announces that it
  started, what it found ("78 % of the area served, peak −61 dBm") or why it
  failed, through a polite `role="status"` region; and all 29 error surfaces
  across 12 files carry `role="alert"`, with warnings as `role="status"`.
- **The indoor DAS tab could not be used without a mouse.** Antenna placement
  existed only as a click on a bare `<img>` — no `tabIndex`, no key handler —
  so a keyboard or screen-reader user could never add one and the Run button
  stayed disabled forever. There is now an explicit *Add antenna at plan
  centre* control plus labelled X/Y fields on each antenna, so the whole
  workflow is reachable without a pointer.
- **Repeated rows had no accessible name.** The DXF wizard emitted the same
  four ids for every control point and the DAS list the same three for every
  antenna, so with three rows nine inputs shared four ids: rows 2 and 3 were
  nameless and every label pointed at row 1's field. Ids are now per-row.

### Fixed — guided mode, and results that outlive their inputs

- **Simple mode hid nothing, and nobody started in it.** The guided mode was
  purely additive: it prepended a scenario grid and still rendered all eight
  expert panels, including the ~25-control Radio study panel — and the app
  booted in Expert, so every first-time visitor was handed exactly what Simple
  mode exists to prevent. First run now starts guided (a stored choice still
  wins), the sidebar keeps only placement and the study, and the study panel
  itself has a compact form: no propagation model, antenna pattern, downtilt,
  clutter, budget overrides, multi-site, frequency plan or capacity — just
  place the points, run, read the result. Six form controls instead of forty.
- **A result outlived the inputs that produced it.** The painted raster, its
  statistics and its PNG/GeoTIFF/KMZ links were invalidated only when the TX
  moved or the technology changed, while a dozen inputs that *are* sent to the
  engine — radius, model, environment, TX height, downtilt, fade margin,
  clutter, WorldCover, DSM, every budget override — were not watched. Raise a
  mast from 20 m to 40 m and the live link budget updated while the heatmap and
  "Served area 62 %" still described the 20 m run, so the GeoTIFF downloaded as
  the 40 m design was the wrong study. A run now records a fingerprint of every
  input it consumed; when the current settings drift from it the result is
  marked stale and **the three exports are withdrawn until it is re-run**.

### Fixed — the panel showed one thing and ran another

- **Equipment and link-budget overrides survived a technology change.**
  Selecting the "Enterprise Wi-Fi AP" profile (23 dBm, −82 dBm, 65° sector)
  and then switching the preset to TETRA 400 left the panel displaying
  *40 dBm · −103 dBm · omni* while the study was dispatched at
  *23 dBm · −82 dBm* inside a 65° wedge — a ~38 dB link-budget error, invisible
  because the override fields are collapsed out of sight by default. Changing
  the technology now clears every override, the readout is labelled
  **Effective** (and shows the values that will actually run) whenever one is
  in force, and a badge on the collapsed section counts them.
- **The guided path ignored most of its own scenario.** `applyScenario` used
  only the technology and the two antenna heights, discarding the `radius_km`,
  `sector` and `shadow_margin_db` that `/api/rf/scenarios/{id}` resolves — so
  Simple mode ran at the default radius with a **0 dB fade margin**, a
  50 %-probability median, where the scenario intended a 90/95 % design margin.
  Presented, of course, to the user least equipped to notice it was optimistic.
  All three are now applied.
- **The 3D toggle was unclickable at every width.** `.view-toggle` sat at
  top-right with `z-index: 500` underneath Leaflet's layers control
  (`.leaflet-top { z-index: 1000 }`), which covered the headline 3D feature
  completely. Moved below the zoom control — whose height is fixed, unlike the
  layers control that grows when expanded — and lifted above the Leaflet
  control layer.

### Added — licensing

- **AntennaMaster is now formally licensed under the GNU AGPL-3.0**
  (`AGPL-3.0-only`). Until now there was no `LICENSE` file, which legally
  means all-rights-reserved: enterprise open-source review boards reject that
  on sight, a consultant could not install it on a client's machine, and
  `docs/MARKET_BENCHMARK.md` was advertising "$0, open source" — a claim the
  repository did not support. The licence is declared in `README.md` (with
  §13's network-use obligation spelled out, since a hosted RF planner is
  exactly the case the plain GPL leaves open) and in `frontend/package.json`.
  PyMuPDF, previously flagged as an AGPL dependency in the runtime image, is
  compatible with this choice.

### Changed — packaging

- **The production image no longer ships a test harness.** `requirements.txt`
  carried `pytest`, `pytest-cov` and `pymupdf` (test-only, ~30 MB) straight
  into the runtime container. Test and tooling dependencies moved to
  `requirements-dev.txt`; the CI jobs that run pytest install that, while the
  end-to-end and launch-path jobs deliberately keep installing only
  `requirements.txt`, so they now double as a check that the runtime set is
  genuinely sufficient to serve the app.

### Fixed — security (usability/benchmark/infosec committee)

- **Cross-tenant disclosure: a tenant could be joined by naming it.** The
  audit log scopes on `users.org_name`, and both that string *and* `role` were
  accepted verbatim from the registration body. Anyone who had seen a
  customer's organisation name — it is printed on every exported report header
  — could register as `role="manager"` of it and read that tenant's entire
  audit log: employee emails, client IPs, actions. In SaaS mode registration
  now refuses an organisation that already exists (409, invite required) and
  only the account that *creates* an organisation administers it; an account
  with no organisation is `field` and has no audit access.
- **Coverage results were readable by id alone (IDOR).** `/coverage/{id}.png`,
  `.tif`, `.kmz` and the `/at` point query took no user dependency, so a
  12-hex id — which travels in share links, PDF footers, audit details and
  proxy logs — returned another tenant's georeferenced site footprint.
  Rasters now record their owner and the four routes go through a
  `resolve_result()` guard returning 404 (not 403) to a non-owner.
  Anonymous/self-hosted results stay open.
- **422 responses echoed the submitted value, including passwords.**
  Registering with a too-short password returned that plaintext password in
  the error body, landing in devtools, proxy logs and error reporters. The
  handler now returns only location, type and message.

### Fixed — trust and safety (committee round 2)

- **EMF exposure was under-reported, on the document that carries a signature.**
  Three FCC OET-65 errors, all in the unsafe direction: the ground-reflection
  factor was applied as ×1.6 to *power density* when 1.6 is the *field*
  factor (S ∝ E², so the correct power factor is ×2.56 — every exclusion zone
  printed **21 % too small**); the occupational MPE used the uncontrolled
  tier's 1.34 MHz breakpoint with an 1800/f² numerator instead of OET-65
  Table 1's 3.0 MHz / 900/f², making the controlled limit **2× too permissive**
  (4.5× at 2 MHz). The dossier defaults to `ground_reflection=True`, so this
  landed in real output. Anchored to every row of OET-65 Table 1 in tests.
- **A report could print a coverage figure supplied by its own reader.**
  `report.pdf` took `served_area_fraction` and `max_rx_power_dbm` from the
  HTTP request body and printed them beside a map rendered from the stored
  raster — so a client could claim 99 % coverage over a map showing far less.
  Both fields are removed and now rejected (422); the engine's own statistics
  are persisted with the raster and read back for rendering. A figure the
  engine did not produce is omitted rather than defaulted to `0`.
- **The ITU accuracy gate could not fail.** The CI step piped `pytest` into
  `tee` under GitHub's default `bash -e` shell (no `pipefail`), so the step
  took *tee's* exit status: a genuinely failing accuracy test reported green,
  and the job could only ever fail on a skip. It now runs under `shell: bash`
  (`-eo pipefail`) and covers all three validation suites instead of one.
- **One bad row destroyed an entire batch.** A receiver co-located with the
  transmitter — the tower itself or a duplicate, present in almost every
  pasted subscriber list — divided by zero in the Deygout helper and
  serialised a non-finite float, returning **500 for the whole request**.
  Degenerate geometry now yields `served: null` with a note explaining why,
  every derived figure nulled (never a finite-but-meaningless "margin
  100 dB"), and the good rows are unaffected. CSV output is properly quoted.
- **Diffraction loss was not reciprocal.** Deygout's shared edge budget was
  spent depth-first, so the left sub-path consumed it before the right was
  examined and the answer depended on which end you called TX: **36 % of
  random multi-ridge profiles disagreed with their own reverse, by up to
  12.8 dB**. Talk-out and talk-in are derived from this number, so the
  asymmetry was visible directly in two-way coverage. The budget is now
  awarded globally strongest-edge-first (which is what Deygout actually
  specifies, and keeps the total-budget semantics), ties are broken on
  terrain properties rather than sample order, and the profile orientation is
  canonicalised so both directions execute the identical path. Verified
  exact over 40,000 randomised profiles with metre-quantised elevations.
  Cost: the per-sample profile study is ~1.6× slower (15 → 24 ms at 256
  samples, 129 → 217 ms at 2048) because candidate edges are now evaluated
  across all open sub-paths instead of abandoned depth-first — an honest
  price for removing a 12.8 dB direction-dependent error.
- **Stored XSS in the Live Ops dashboard.** Telemetry asset names were
  interpolated into a Leaflet `DivIcon`, which assigns to `innerHTML`, so an
  ingested name like `"><img src=x onerror=…>` executed in every open
  dashboard. Escaped at the sink.

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

### Changed
- **Area coverage now diffracts with Deygout multi-edge, like the profile and
  ITM paths already did.** The coverage kernel took only the strongest single
  knife edge on each TX→step sub-path while the README advertised Deygout.
  Measured against the scalar reference on synthetic terrain that was ~15 dB
  optimistic over one ridge and ~30 dB over three — in exactly the multi-ridge
  terrain a coverage study exists to characterise — and every derived product
  inherited it (best-server, SINR, throughput, site search, batch CPE
  qualification, two-way talk-back, served-area fraction). The kernel now takes
  the principal edge plus one secondary per sub-path and agrees exactly with
  the reference up to two obstructing edges. **Served-area figures will drop
  for obstructed sites; the old numbers were optimistic.** The heaviest
  benchmark got faster and leaner in the process (5.3 s → 3.9 s, 176 → 103 MB)
  by hoisting the radial-independent geometry out of the chunk loop.

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
