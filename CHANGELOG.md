# Changelog

All notable changes to AntennaMaster are recorded here. Versions follow
[semantic versioning](https://semver.org/); the version shown is the app /
Windows-installer version (`dist/AntennaMaster-Setup-<version>.exe`).

## 1.3.5 — 2026-08-27

### Fixed — a signed-in user could not see or download their own coverage

This is the product's central output, and it was broken for exactly the
people who had signed in. Anonymous self-hosted use kept working, which is
why nothing caught it.

- Coverage results are owner-scoped: a result id is not a capability, because
  it travels in share links, PDF footers, audit fields and proxy logs, and
  treating it as authorisation leaked other tenants' georeferenced site
  footprints. The backend answers 404 to anyone who is not the owner —
  correctly. **The gap was on the browser side:** the raster is loaded as an
  `<img>` (Leaflet's ImageOverlay, Cesium's single tile) and the exports were
  `<a download href>`. Neither can carry a header, and the token lives in
  localStorage rather than a cookie, so a signed-in user's request for their
  own result arrived unauthenticated and was refused.
- Measured on a freshly computed study while signed in: **`.png`, `.tif` and
  `.kmz` all 404 as the interface loaded them, and all 200 with the bearer
  token.** The coverage overlay sat in the DOM with `naturalWidth: 0` — a
  broken image, nothing painted — and each export button saved the body of a
  404 under the right filename: a `coverage.kmz` Google Earth refuses to
  open, with no error shown anywhere.
- These artefacts are now fetched with the account's credentials and handed
  to the browser as blobs. **The token deliberately does not move into the
  query string** — the backend's own note on this says these URLs end up in
  proxy logs and share links, and a bearer token there is strictly worse than
  the id it was protecting.
- Applies to the 2D map overlay, the georeferenced DXF hillshade, the 3D
  globe's draped coverage, and the PNG / GeoTIFF / KMZ exports. Verified in
  the browser signed in: the raster paints (`naturalWidth: 512`) and the
  three exports save 13.9 kB, 11.2 kB and 13.7 kB of real file.
- Anonymous deployments send no header and get the same bytes, so this is not
  a SaaS-only path.

## 1.3.4 — 2026-08-27

### Fixed — the tactical view claimed to be online when nothing was reachable

- **The connectivity badge now asks the backend, not `navigator.onLine`.**
  That flag reports whether a network interface exists, not whether anything
  can be reached, and the two come apart in exactly the situation this screen
  is for: a site LAN with no route out, a hotspot with no upstream, a captive
  portal. The badge read "● Online" regardless — on the screen a technician
  checks *before they climb*, where believing the terrain service is
  reachable and being wrong is the expensive direction.
- **A failed request is better evidence than any probe**, so the GPS spot
  check's own elevation lookup now sets the state directly: if that call
  failed, the link is down, whatever the browser thinks.
- The probe requires a healthy answer, not merely an answer. Measured with
  the backend stopped, the web app's own proxy returns **HTTP 500** rather
  than failing the request — so "we got a response" would have put "Online"
  on the badge with the backend dead, which is the same mistake one layer
  down. `navigator.onLine === false` is still trusted in the negative
  direction: when it fires it is right, and it saves a doomed request.
- Verified in the browser: with the backend killed, the badge flips to
  "○ Offline — cached" within one probe interval while `navigator.onLine`
  stays `true` throughout.

## 1.3.3 — 2026-08-27

### Fixed — the pitch screen's payback contradicted the coverage beside it

- **Return on investment now answers to the served area.** The ROI used only
  the revenue figure the user typed and the equipment cost; the served-area
  fraction was printed in the next KPI box but never entered the calculation.
  So a design that covers a tenth of the target site — a design that failed —
  was handed to a buyer with an attractive payback, and the option covering
  seven times more area was credited with nothing for it. Their paybacks
  differed only because their radios cost different amounts.
- Measured on the screen itself, comparing Private LTE B48 against Wi-Fi 5.8
  PtMP at the same site: **10% served area, 5.9 months payback, +$394k** in
  one KPI row. The same option now reads **387.9 months and −$36k**, and the
  72%-coverage option reads 1.3 months and +$334k — which is what the two
  designs are actually worth relative to one another, and the whole point of
  a screen that puts them side by side.
- **The assumption is stated on the card**, because scaling revenue by
  coverage is a modelling choice, not a fact: "revenue is earned only where
  there is coverage: 72% of the area served → $5,764/mo of the figure above."
  An assumption the reader cannot see is an unsupported number wearing a
  different hat. The revenue input is relabelled "Revenue $/mo at full
  coverage" to match.
- With no coverage result there is now no payback figure at all, rather than
  a confident number with nothing behind it. And a five-year loss renders as
  −$36k instead of $-36k, which on a slide read like a typo.
- At 100% served area the calculation is exactly the previous one, so figures
  already trusted for a fully-covering design do not move.

## 1.3.2 — 2026-08-27

### Fixed — the offline base map never actually engaged

- **The fallback now triggers on tiles that fail, not on `navigator.onLine`.**
  That flag reports whether a network interface exists, not whether the tile
  provider can be reached — and the two come apart in exactly the deployment
  this product is for: an OT/field machine on a LAN with no route out, behind
  a corporate proxy, or on a captive portal. Observed while driving the app:
  `navigator.onLine === true` while every CDN tile failed, so the locally
  cached tiles — the headline offline feature — were never swapped in, and the
  planner drew a real coverage study over a blank grey rectangle.
- **And it now says so.** A degraded base map looks exactly like a broken
  application, which matters more here than in most tools because what the
  user is looking at is about to be filed. The notice names which half is
  affected: the tiles are missing, the terrain and the coverage behind the
  study come from the local elevation data and are not.
- Failures from the local cache layer are excluded from the count, or a cold
  cache would feed the trigger from the very layer the fallback installs and
  the state could never clear.

### Fixed — the live fleet list grew without bound

- **An asset silent for an hour now leaves the live twin.** Sharing the
  telemetry state in 1.3.1 also made it durable, and durable turned a
  harmless quirk into a leak: an asset was flagged as no longer transmitting
  at 30 s and then stayed in the fleet list forever, where before a restart
  cleared it. The panel an operator scans during an incident filled with
  vehicles that stopped mattering days ago. The two thresholds answer
  different questions and cannot be one number — 30 s means "this radio just
  dropped", an hour means "this is not part of the live fleet". The
  disconnect stays in the event log, which is the record; the asset list is
  the *live* picture.

### Fixed — Ctrl-C left both servers running

- `start.sh` ended on a bare `wait`, so the signal reached the shell and the
  children kept holding the ports — and the new port guard then refused the
  next start. Both launchers now stop the whole process tree: `uvicorn
  --workers 2` is a supervisor with two children of its own, and killing only
  the parent orphans them (reproduced: two workers left holding :8010).

## 1.3.1 — 2026-08-27

Three defects that only a *running* installation can show — every one of them
passed the whole test suite, and every one of them was found by launching the
app and using it.

### Fixed — the live twin was a different world in each worker

- **Telemetry state is now shared across uvicorn workers** (SQLite, one row per
  tenant) instead of living in a module-level dict. The documented launch path
  runs `--workers 2`, so a ping ingested by worker A was simply absent when
  worker B served the next read. Measured on the running stack: eight
  consecutive `/state` reads after one ingest returned **2, 1, 2, 2, 2, 2, 2,
  2** assets; the dashboard showed a fleet flickering in and out of existence.
  Now `1, 1, 1, 1, 1, 1, 1, 1`.
- **Timestamps are wall clock, not `time.monotonic()`.** Monotonic's epoch is
  arbitrary and *per process*; the moment those numbers crossed a worker
  boundary an asset looked either impossibly stale or stale in the future, so
  the 30 s disconnect sweep fired at random. Monotonic was the right choice
  while the state never left the process — it stopped being right when it did.
- The RF predicate closes over the terrain service and cannot be serialised, so
  the coverage *request* is what is stored and each worker rebuilds its own.
  A worker that never handled the binding still correlates.

### Fixed — the Live Operations stream never reached the browser

- **`Content-Encoding: identity` on the SSE response and `compress: false` in
  the web app.** Anything between browser and backend that buffers — Next's own
  gzip here, but equally nginx without `proxy_buffering off` — holds every
  frame of an infinite response forever. Measured through the app's own proxy:
  the backend delivered the first frame in 0.0 s while the browser received
  nothing at all, ever.
- **And the dashboard now makes the stream prove itself.** The failure above
  was survivable only because it was *silent*: the connection succeeded, so
  `onerror` never fired and the polling fallback never engaged. A stream that
  delivers no frame within 4 s is now treated as broken and polling takes over
  — which is the case that matters behind a proxy nobody told us about.

### Fixed — a stale build could be served silently

- **`start.sh` rebuilds when the sources are newer than the build**, not only
  when there is no build at all; **`launch.sh` / `launch.ps1` refuse to start**
  on that mismatch and name the command that fixes it; and **the Windows
  installer deletes the previous web build** before writing new sources over
  it, so the mismatch cannot arise from an in-place upgrade. This is the worst
  failure mode a launcher has: it exits 0, prints "up", every route answers
  200, and the application is the one from before the change.

### Added

- **Desktop shortcut** (optional, on a new components page) alongside the
  existing Start-menu launcher entry — an icon to double-click is what people
  look for after an install.

## 1.3.0 — 2026-08-27

### Added — ITU-R P.1812 as an area-coverage engine

- **The official ITU-R Study Group 3 reference implementation now runs over
  the whole fan** (`model: "p1812"`), not only point-to-point. Alongside ITM
  rather than instead of it, because they are checkable against different
  things: ITM is what the incumbent planning tools run, so a reviewer can
  reproduce a study in their own tool; P.1812 is what a European regulator's
  own coordination is based on, so a study is checkable against the
  Recommendation itself.
- **Clutter goes in as the Recommendation's own input.** P.1812 takes
  representative clutter height as a separate `R` array next to *bare*
  ground. Our Deygout path legitimately raises the obstacle surface by the
  canopy instead — doing both would apply the same trees twice, so the
  P.1812 branch passes bare terrain and hands the WorldCover heights to `R`.
- **Native time *and* location percentages.** ITM needed the right
  variability mode before its reliability quantile meant anything over an
  area; P.1812 takes `pT` and `pL` directly, so "the level exceeded at 95% of
  locations, 50% of the time" — the form a coverage obligation is written in
  — is the Recommendation's statement rather than ours.
- **A deployment without the ITU digital maps answers 503 and names the
  install command.** The maps are ITU integral products and are not
  redistributable, so a self-hosted install may legitimately lack them.
  Quietly substituting another model — on a study someone will file — would
  be worse than refusing.
- Below 250 m, outside P.1812's stated range, the study falls back to free
  space and says so. Cost is ~0.5 ms per sample (≈10 s for a default
  180×100 sweep); the benchmark gate measures it where the maps exist and
  **prints a visible SKIP** where they do not, because a gate that silently
  disappears reads exactly like one that passed.

### Changed

- The ITU reference engines are pinned by commit in `requirements.txt` too,
  matching CI and both installers.

## 1.2.0 — 2026-08-27

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

### Fixed — live telemetry was world-readable and world-writable

- **Every `/api/telemetry/*` route was unauthenticated against one
  process-global engine.** Live asset positions are the real-time locations of
  responders, mine crews and field staff, so anyone who could reach the backend
  could read another operator's fleet and inject forged pings into it. In SaaS
  mode telemetry now requires an authenticated caller and each organisation
  gets its own isolated engine (the WebSocket closes with 1008 rather than
  silently accepting). A self-hosted single-tenant deployment keeps the shared
  engine and stays open — the same rule the DXF and coverage-result guards
  already follow, so the local Live Ops demo is unaffected.

### Added — a model tuning is a named site asset, not a blob you paste around

- **`/api/rf/calibrate` fitted a correction and handed back coefficients.**
  Applying it to the next study meant carrying that object by hand: nobody
  could tell which tuning a filed study used, last quarter's drive test was
  gone, and nothing on screen tied "+6.2 dB" to the measurements behind it.
  Calibrations are now saved under a name, owner-scoped, listed and reusable
  — `calibration_id` on a coverage request applies one, and the study of
  record captures *which*.
- **The evidence travels with the coefficients.** A correction is credible
  because of the measurements behind it, so the point count, the distance
  span and the RMS error before and after are stored with the fit and shown
  in the picker. A name alone cannot warn anyone that an offset came from
  six points on another band.
- **Reusing a fit across bands is allowed but never silent.** A planner may
  legitimately carry a site's clutter correction to another technology;
  applying it without a word would be the tool asserting a physical claim
  the measurements do not support, so the study comes back with a warning.

### Added — every study is now a study of record

- **A coverage raster kept its bounds, mast position, radius and headline
  statistics — and nothing else.** Enough to redraw the picture, nothing like
  enough to defend it: the frequency, model, antenna, margins, clutter and
  weather assumptions, terrain source and engine versions all vanished when
  the request finished. Two studies a month apart could differ by 20 dB with
  nothing on the artefact to say why — and a coverage plot is evidence, read
  months later by someone who was not in the room. Each study now stores its
  **complete input set** and its **provenance** (application version,
  propagation engine, terrain source, which reference engines the deployment
  could reach) with a **16-hex digest** over both.
- **`GET /api/rf/coverage/{id}/record`** returns it, owner-scoped like every
  other read of the raster, and the digest is printed on the exported PDF —
  a plot a reader cannot ask questions about is just a picture.
- **`POST /api/rf/coverage/{id}/rerun`** answers the question a reviewer
  actually asks after a DEM refresh or a release: not "what did you run" but
  "does it still say that". It re-executes the recorded inputs verbatim and
  reports whether the answer moved, as a **new** study with its own id and
  digest. The filed one is never touched — an edited study of record is not
  one. A study predating the format answers 404 rather than a reconstructed
  record, because a record assembled after the fact from partial metadata is
  a guess wearing the clothes of evidence.

### Added — ITM / Longley-Rice as a coverage engine, not only a link tool

- **The area sweep offered only empirical curves.** Hata, COST-231 and
  TR 38.901 are fitted curves plus our own Deygout diffraction; ITM is the
  algorithm regulators and the incumbent tools (SPLAT!, Radio Mobile, TAP)
  actually run, and a consultant's study is defensible partly because a
  reviewer can reproduce it in their own tool. It was reachable here only
  point-to-point. `model: "itm"` now runs it over the whole fan — one full
  Longley-Rice run per sample over the profile out to that sample, the same
  recipe SPLAT! builds a coverage plot from. ~2.4 s for a default 180×100
  study, gated in the benchmark suite.
- **No double-counted terrain.** ITM derives the terrain effect itself, so
  the sweep adds no Deygout term on top of it. Getting this wrong would have
  produced a study tens of dB pessimistic behind every ridge — and it would
  have looked plausible, because coverage behind a ridge *is* poor.
- **The reliability quantile is the point, and it needed the right
  variability mode.** An area study uses ITM's `mdvar=2` ("mobile"), where
  the receiver could be anywhere in the pixel — not the point-to-point mode,
  which suppresses location variability because both terminals sit at known
  places. With the p2p mode a 90% study came out **0.7 dB** below the
  median: a reliability knob that appears to work and does not. In mobile
  mode the same 90% costs **~12 dB**, which is the number a licence
  application or a coverage SLA is written on. The median is identical
  either way, so the pinned point-to-point validation is untouched.
- Inside 1 km — below ITM's stated range, where it raises its own
  out-of-range flag rather than refusing — the study falls back to free
  space and says so, instead of painting an unsupported number over the
  busiest part of the map.

### Fixed — a request could hang forever with nothing on screen

- **Every API call was a bare `fetch`, which has no timeout.** On the
  hardware this is used on — a tablet that walks out of coverage mid-study —
  the promise simply never settles: the UI sat on "Simulating…" with no
  result, no error and no way back except a reload. All 35 call sites now go
  through one wrapper with an `AbortController` budget (30 s for metadata,
  180 s for a full-resolution sweep or an upload), and the failure says what
  to do — "try again, or reduce the radius or resolution" rather than
  `AbortError`. A dropped connection reports as one instead of
  "Failed to fetch", and a deliberate cancel is passed through rather than
  being relabelled a timeout.

### Added — the cluster study can finally be edited, imported and exported

- **A site could be added and removed but never corrected.** A mistyped
  coordinate or a wrong azimuth meant deleting the row and re-clicking the
  map, which on a twelve-site estate is how people give up on a tool. Each
  site now expands into an editor for its name, coordinates, azimuth and
  downtilt.
- **The per-site radio overrides existed only in the API.** The backend has
  accepted per-transmitter `freq_mhz`, power, gains, losses, sensitivity,
  heights and beamwidth since the cluster-study work — but the UI cloned one
  preset across every site and `simulateMultiCoverage` *stripped the fields
  on the way to the wire*, so an 800 MHz macro layer next to a 3.5 GHz
  capacity layer still ran as one preset. The editor exposes all nine, blank
  meaning inherit (a field pre-filled with the inherited number reads as a
  decision someone made), a badge marks which sites differ from the study,
  and the serializer is now shared so a new caller cannot drop them again.
- **CSV import and export are wired up.** `POST /api/rf/sites/parse-csv` and
  its lossless inverse were reachable only by curl. An OSS export now loads
  straight into a study, and every rejected row is listed with its line
  number and reason — a planner who imports 40 sites and studies 38 has to
  be told which two.

### Fixed — a compliance PDF could be rewritten by the site name typed into it

- **User text reached ReportLab's markup parser unescaped.** A `Paragraph`
  parses a small HTML dialect, so every site name, operator, note, project
  title and organisation on a report header was markup. An ordinary mast
  name like `Mast A & B <north>` rendered as `Mast A & B` — the parser
  swallowed `<north>` as an unknown tag, putting the wrong structure on a
  document that gets signed and filed — and some inputs raised a hard
  `ValueError` from the parser instead of producing a report at all. Worse,
  the input could restyle the page: `<font color="white">` hides text and
  `<img src=...>` pulls in a local file, on a dossier whose whole purpose is
  to state a compliance distance to a regulator. All of it is escaped now,
  through one shared function rather than a habit.

### Hardened — CI supply chain

- **`permissions: contents: read`** on the workflow. The default was
  whatever the repository setting says, historically read/write on
  everything, so any step — or anything one of them installed — could push
  to the repo or edit releases. No job here writes to GitHub.
- **The ITU-R reference engines are pinned by commit** in CI and in both
  installers. They are third-party sources with no signature and no
  lockfile, and they *are* the implementations our accuracy claims are
  measured against: an unpinned `git+https://…` ran whatever HEAD was when
  CI happened to fire, so an upstream change could have moved the numbers we
  validate against — or run arbitrary `setup.py` code — with no diff on our
  side.

### Fixed — a gated preset was only gated on one router

- **`/api/terrain/*` never checked preset entitlements.** `/api/rf/coverage`
  refused an enterprise-only private-LTE preset to a basic account, but the
  terrain router took the same `technology=` parameter and let it straight
  through — so the same account could run the gated model as a full
  path-loss + Deygout diffraction study through `/api/terrain/profile`,
  `/itm`, `/optimize-heights`, and export it as CSV.
  `/api/terrain/availability` was worse: its technology *defaults* to
  `ptp18000`, itself a Pro preset, so the plain default call was the bypass.

### Added — the expensive endpoints are no longer an unlimited free resource

- **No quota, no queue, no throttle on anything heavy.** A coverage study is
  seconds of CPU plus a burst of DEM fetches, and it was reachable
  unauthenticated in a loop — a free denial of service against every other
  tenant on the box, with the upload routes doing the same to the disk
  (100 MB per DXF). A central middleware now applies a sliding-window limit
  (compute: 20/min anonymous, 60/min signed-in; uploads: 5/h and 40/h) and
  answers 429 with `Retry-After`. The bucket is keyed by account when the
  token resolves and by client IP otherwise, so varying a garbage
  `Authorization` header does not mint a fresh budget. `AM_RATE_LIMIT=0`
  turns it off for an air-gapped box with one engineer on it.

### Fixed — the offline cache handed one account's data to the next

- **The PWA cached every API response in a single URL-keyed bucket.** The
  Cache API matches on URL and `Vary`, never on `Authorization`, and nothing
  cleared it at sign-out — so on the hardware this product is actually
  deployed on, a shared rugged tablet passed between a field crew, technician
  A could sign in and open their projects and the org audit log, sign out,
  and the next person to lose signal would be served A's studies and every
  colleague's email and client IP by the offline fallback. Each identity now
  gets its own cache bucket (named by a truncated hash of the bearer token,
  never the token itself), `/api/auth/*` and `/api/telemetry/*` are never
  cached at all, and signing out purges every API bucket — while keeping the
  public basemap tiles a field tablet needs at the bottom of a pit.

### Added — share links that expire and can be taken back

- **A share link was permanent and irrevocable.** It opens a saved study —
  site coordinates, customer name, the whole design — to anyone holding the
  URL with no login, and once minted there was no way to withdraw it: a link
  mailed during a tender still opened years later, and forwarding it to a
  competitor could not be undone. New links now expire in 30 days (the owner
  may opt out explicitly), re-sharing rotates the token so the old link dies,
  and there is a Revoke button. An expired link answers 404 with the same
  wording as an unknown one, so it never confirms the project exists.

### Added — users can get their data out, and get themselves deleted

- **Account & privacy (GDPR art. 15, 17, 20), self-serve.** There was no
  delete path at all — closing an account meant asking an operator to run SQL
  — and no way to obtain a copy of your own data. `GET /api/auth/export`
  returns the profile, every saved project *with its full study payload* and
  the caller's own audit rows as one JSON file; `DELETE /api/auth/account`
  (password **and** a typed `DELETE`, because a bearer token is what an
  unlocked laptop hands over) destroys the account and everything it owns.
  That deliberately means more than the user row: the uploaded site CAD, the
  rendered coverage rasters and their `.npz` sidecars, private antenna
  patterns and the white-label logo are all unlinked, along with the
  in-process raster cache that would otherwise keep serving a deleted file.
  The response is a receipt of what went, not a bare 204.
- **The audit trail is pseudonymised rather than deleted.** An operator must
  still be able to answer "who changed this site's power?" after a
  contractor leaves, so the rows survive under a random opaque `subject`
  (stable across that person's history, unlinkable back to them) with the
  client IP nulled. They keep the *organisation* name — an org identifies a
  company, not a person — or the whole history would have silently vanished
  from its own manager's audit view the moment someone closed their account.
- **Audit retention.** `audit_log` had no TTL and no pruning, so a deployment
  accumulated emails and client IPs indefinitely with no stated policy. Rows
  older than `AM_AUDIT_RETENTION_DAYS` (default 365) are now pruned on boot
  and at most hourly on the write path; `0` opts an air-gapped install out.

### Added — a cluster study can finally describe a real network

- **Per-transmitter radio parameters.** `/coverage/multi` (and the frequency
  plan, capacity map and Monte-Carlo endpoints) cloned **one** technology dict
  across every site, and a site carried only lat/lon/name/azimuth/downtilt. A
  real estate — an 800 MHz macro layer, a 3.5 GHz capacity layer, a 400 MHz PMR
  overlay, each with its own power, mast height and antenna — was therefore
  inexpressible, and the composite described a network that does not exist.
  **Six committee personas independently called this a blocker**, more than any
  other finding. Each site may now set `freq_mhz`, `tx_power_dbm`,
  `tx_gain_dbi`, `rx_gain_dbi`, `losses_db`, `rx_sensitivity_dbm`, `h_bs_m`,
  `h_ut_m` and `antenna_beamwidth_deg`; anything omitted inherits the
  request-level value and then the preset, so an existing caller is unaffected.
  The response echoes what each transmitter *actually* ran on, so an override
  can never be confused with one that was silently ignored.
- **Site inventory as CSV.** `POST /api/rf/sites/parse-csv` turns an OSS export
  into the `sites` array a study takes, and `POST /api/rf/sites/export-csv` is
  its lossless inverse. Unknown columns are ignored and blank cells inherit,
  but every rejected row is reported with its line number and reason rather
  than dropped in silence. Clicking 200 coordinates onto a map one at a time
  was not an onboarding path.

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
