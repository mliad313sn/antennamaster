# AntennaMaster — Security & Compliance

How the platform meets OT/IT expectations for access control, audit logging
and data handling. Companion to `SaaS_ARCHITECTURE.md` (tenancy internals)
and `DEPLOYMENT_GUIDE.md` (hardening at deploy time).

---

## 1. Role-Based Access Control (RBAC)

Access is governed by two independent axes — **role** (what dashboard/actions
a user gets) and **tier** (what capabilities are entitled) — plus **resource
ownership**.

### Roles
| Role | Landing experience | Intent |
|---|---|---|
| `manager` | Command Center (`/dashboard`) | portfolio, cost/ROI, **org audit log**, branding |
| `field` | Tactical View (`/field`) | on-site GPS validation, offline use |
| `presales` | Pitch (`/pitch`) | A/B scenarios, executive PDF |

The role is set at registration (validated against `^(manager|field|presales)$`)
and is the only axis that gates the **audit log** — `GET /api/auth/audit`
returns `403` unless `role == manager`.

### Tiers (capability entitlements)
`basic → pro → enterprise`, enforced by `require_feature()` / `check_preset
_allowed()`. Feature keys map to a minimum tier (e.g. `dxf_fusion`, `pdf_export`,
`indoor_studio` → pro; `private_networks`, `multi_site`, `api_access`,
`white_label` → enterprise). In **SaaS mode** (`AM_SAAS_MODE=1`) a gated call
without the entitlement returns **HTTP 402** with the required tier; in open
(self-hosted) mode nothing is gated.

**Tier changes are not self-serve in SaaS mode.** `POST /api/auth/tier`
requires the `X-Billing-Secret` header to match `AM_BILLING_SECRET` — a user
cannot grant themselves Enterprise; only the billing provider's webhook can.

### Resource ownership (cross-tenant isolation)
**Coverage results** are owner-scoped at the store: `results_store` records the
owner with each raster and `resolve_result()` fronts `/coverage/{id}.png`,
`.tif`, `.kmz` and the `/at` point query, answering **404** (not 403) to a
non-owner so an id is not an existence oracle. This matters because a result id
is not a secret — it travels in share links, exported PDF footers, audit detail
fields and reverse-proxy logs — and those four routes previously took no user
dependency at all, so holding a 12-hex id yielded another tenant's
georeferenced site footprint. Results with no owner (the anonymous self-hosted
default) stay readable, exactly like an anonymous DXF.

Every consumer of a DXF, antenna pattern or async job is guarded so one tenant
cannot read another's data by guessing an id:
- **DXF**: a central `resolve_dxf()` guard runs existence (404) → **owner
  check (403)** → tier gate (402) → ready (409) on *every* DXF-consuming
  endpoint (terrain profile/elevation, coverage single/multi/batch/site-search,
  indoor coverage/preview, height optimizer, KML export, and the DXF-native
  `layers` / `overlay.png` / `state` reads — the reads are owner-scoped without
  the tier gate so an anonymous self-hosted session can still restore its own).
- **Antenna patterns**: owner-scoped load — a private pattern cannot be *used*
  by another account (403), not merely hidden from listings.
- **Async jobs**: `GET /api/saas/jobs/{id}` is owner-scoped and returns **404**
  (not 403) to a stranger, so ids are not an existence oracle.
- **Projects**: get/update/delete/share/duplicate all check `user_id`; shared
  links strip the owner id and the capability token from the response.
- **Live Ops telemetry** (`/api/telemetry/*`) is now authenticated and
  tenant-scoped. Live asset positions are the most sensitive data the product
  handles — the real-time locations of responders, mine crews and field staff —
  and every telemetry route was previously unauthenticated against one
  process-global engine, so anyone who could reach the backend could read
  another operator's fleet and inject forged pings into it. In SaaS mode each
  organisation gets its own isolated engine and an unauthenticated caller is
  refused (401; the WebSocket closes with 1008). A self-hosted single-tenant
  deployment keeps the shared engine and stays open, the same rule the DXF and
  coverage-result guards follow. Regression:
  `test_telemetry_requires_auth_and_is_tenant_scoped_in_saas`.
  *Note:* the SSE stream additionally accepts `?token=` because `EventSource`
  cannot set headers; a token in a URL reaches proxy logs and browser history,
  so every other route should use the `Authorization` header.

### Authentication
- Passwords: **PBKDF2-HMAC-SHA256, 200k iterations**, per-user salt, constant-
  time comparison (`hmac.compare_digest`).
- Sessions: opaque bearer tokens, **30-day TTL**, revoked on logout; expired
  tokens are purged on use.
- Brute-force guard: **8 failures / 15 min** per account locks further
  attempts (HTTP 429).

---

## 2. Audit logging

A centralized **FastAPI middleware** (`AuditMiddleware` in `app/main.py`,
backed by `app/services/audit.py`) records every critical action — no endpoint
has to remember to log.

### What is recorded
Logins, registrations, logouts, tier changes, API-token creation, logo
uploads, **DXF uploads / georeferencing / deletion**, antenna uploads,
**project create / update / delete / duplicate / share**, and **every data
export** (CSV, KML, KMZ, GeoTIFF, BOM, PDF, async coverage, batch analysis).

### What is stamped
Each record carries: **action, user id, email, client IP, HTTP status,
timestamp, detail**. The client IP is the left-most hop of `X-Forwarded-For`
(behind a reverse proxy) or the direct peer. Only successful actions
(status < 400) are recorded, so a failed login is never logged as a success;
the login itself is attributed to the resolved account (the request carries no
token yet, so the endpoint stamps identity via `request.state`).

### Where it goes (two sinks)
1. **File** — `AM_DATA_DIR/audit.log`, via Python's `logging` module with a
   `RotatingFileHandler` (5 MB × 5), append-only, **mode 0600**. This is the
   stream to ship to a SIEM.
2. **Database** — the tenant-scoped `audit_log` table. `GET /api/auth/audit`
   (manager only) returns entries **scoped to the caller's organization** in
   SaaS mode — a manager never sees another tenant's emails or activity.

   That scoping keys on `users.org_name`, so in SaaS mode **an organization
   cannot be joined by naming it**: registration refuses an org name that
   already exists (409 — an existing administrator must invite you), and only
   the account that *creates* an organization gets the `manager` role. An
   account registered without an organization is `field` and has no audit
   access at all. Before this was enforced, both `role` and `org_name` were
   accepted verbatim from the registration body, so anyone who had seen a
   customer's organization name — it is printed on every exported report
   header — could register as its manager and read that tenant's entire audit
   log. Regression: `test_tenancy_cannot_be_joined_by_asserting_an_org_name`.
   *Known gap:* the 409 makes org names enumerable (they are already
   semi-public, appearing on exported reports), and invite tokens are not yet
   implemented — a second member must currently be added out of band.

Auditing is best-effort with respect to request handling: an audit-write
failure is caught and logged, never propagated, so it cannot break a user
request.

---

## 3. Data handling & isolation

### Storage layout (single data root)
All state lives under `AM_DATA_DIR` (a Docker volume or a bare-metal path):

| Path | Contents | Permissions |
|---|---|---|
| `saas.db` | accounts, tokens, projects, **audit** | **0600** (owner-only) |
| `audit.log` | audit trail | **0600** |
| `dxf_store/` | uploaded site DXF drawings / floor plans | **0700** |
| `results/` | rendered coverage/indoor rasters | **0700** |
| `dem_cache/`, `dsm_cache/`, `basemap_tiles/` | public map/elevation tiles | default |
| `logos/` | white-label logos | default |

Confidential customer data (site CAD, rendered results) and the credential/
audit database are created **owner-only** at startup (`os.chmod` 0700/0600),
keeping other local users off them (data-at-rest isolation). Permission
tightening is best-effort and no-ops on filesystems without POSIX modes.

### Input safety
- Upload caps: DXF ≤ 100 MB (`AM_MAX_DXF_MB`), antenna ≤ 2 MB, logo ≤ 1 MB
  with a PNG/JPEG magic-byte check.
- All id-derived file paths (`dxf_id`, `result_id`, `antenna_id`, `job_id`)
  are sanitized to `isalnum()` before path construction — no traversal.
- Every SQL statement is parameterized; dynamic column updates draw from a
  fixed allow-list.
- Backend errors are wrapped (DEM/parse failures → 502/422 with a short
  message); full tracebacks are logged server-side only, never returned.

### Deployment isolation
Run the backend as a **non-root** user (the Docker image and the systemd unit
both do). Bind the API to localhost and front the app with an HTTPS reverse
proxy; set `AM_CORS_ORIGINS` to your domain. See `DEPLOYMENT_GUIDE.md`.

---

## 4. Offline / air-gapped data handling

For remote or secure industrial sites with no internet:
- **Container images** ship as a `.tar` (`deploy/package_offline.sh`) and load
  without a registry — no external pulls at the site.
- **Base maps** are pre-downloaded per bounding box
  (`tools/download_basemap.py`) into the local tile server
  (`/api/basemap`); the frontend falls back to these cached tiles
  automatically when the browser is offline, and the PWA service worker caches
  the app shell + tiles for full offline operation.
- **Elevation** uses on-demand SRTM tiles; pre-warm the DEM cache on a
  connected machine and copy the `am_data` volume, or point `AM_DEM_URL` at an
  internal mirror, for a fully disconnected deployment.
- No telemetry or external analytics: the only outbound calls are to the
  configured map/elevation tile sources (all overridable to internal mirrors).

---

## 5. Verification

The security posture is covered by automated regression tests
(`backend/tests/`):
- `test_security_hardening.py` — tier-escalation blocked, org-scoped audit,
  logout revocation, login lockout, DXF/antenna/job cross-tenant IDOR on every
  consumer path, share-token stripping, `dxf_fusion` gate.
- `test_audit_middleware.py` — critical actions recorded with user id + client
  IP to file and DB; non-critical reads not logged; failed logins not recorded
  as success; audit file is owner-only.

Run the full gate with `./start.sh --check`.
