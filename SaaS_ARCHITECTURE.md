# SaaS_ARCHITECTURE — Multi-tenant, Monetization & Role UX

## 1. Deployment modes

| Mode | Trigger | Behavior |
|---|---|---|
| **Open (self-hosted)** | default (`AM_SAAS_MODE` unset) | every capability available without an account; accounts still add projects/PDF branding |
| **SaaS** | `AM_SAAS_MODE=1` | anonymous = Basic; gated features require login + entitlement (HTTP 402 with an upgrade message) |

## 2. Database schema (SQLite WAL at `DATA_DIR/saas.db`; PostgreSQL-portable)

```sql
users     (id PK, email UNIQUE, name, password_hash,        -- PBKDF2-SHA256, 200k iters
           role   CHECK IN ('manager','field','presales'),
           tier   CHECK IN ('basic','pro','enterprise'),
           org_name, logo_path, created_at)
tokens    (token PK, user_id FK, kind CHECK IN ('session','api'), created_at)
projects  (id PK, user_id FK, name, kind, data_json,        -- full planner session state
           share_token UNIQUE, created_at, updated_at)
audit_log (id PK, user_id, action, detail, ts)              -- OT/IT compliance trail
```

Simulation artifacts (rasters, DXFs, antenna patterns, jobs) stay on the
existing disk stores; the DB holds identity + metadata only.

## 3. Tiers & entitlements (`services/saas/tiers.py`)

| Feature | Basic (free) | Pro ($79/mo) | Enterprise ($299/mo) |
|---|---|---|---|
| SRTM terrain, Wi-Fi/PMR/broadcast presets, profiles & coverage | ✅ | ✅ | ✅ |
| Saved projects | 3 | 25 | unlimited |
| DXF terrain fusion (georeferencing) | — | ✅ | ✅ |
| PtP/PtMP backhaul preset (rain/gas nuances) | — | ✅ | ✅ |
| Indoor/underground studio | — | ✅ | ✅ |
| Branded PDF reports | — | ✅ | ✅ |
| Private LTE/5G presets (CBRS, n77, NB-IoT) | — | — | ✅ |
| Multi-site best-server | — | — | ✅ |
| Long-lived API tokens | — | — | ✅ |
| White-label logo on reports | — | — | ✅ |

Enforcement is a per-endpoint dependency (`require_feature`,
`check_preset_allowed`, project quota check) returning **402** — the same
hook a billing provider's webhook would toggle. Plan changes via
`POST /api/auth/tier` are self-serve in open mode only; SaaS mode requires
the billing-webhook secret (see §8).

## 4. Role-based UX (Next.js routes)

| Route | Persona | Contents |
|---|---|---|
| `/` | everyone | full planner (map, studies, DXF, indoor studio) + auth chip + Save-as-project |
| `/dashboard` | **IT/OT Manager** — Command Center | project portfolio (open/duplicate/share/delete), CAPEX/OPEX estimator with 5-yr TCO KPIs, plan & white-label management, compliance audit log (manager-only) |
| `/field` | **Field Tech / RF Engineer** — Tactical | forced high-contrast dark mode, oversized touch targets, GPS spot check (position + ground ASL + accuracy), follow-me mode, one-tap presets (VHF/PMR/TETRA/µW PtP/Wi-Fi/CBRS) that seed the planner |
| `/pitch` | **Pre-Sales Architect** — Pitch | scenario A vs B coverage with live progress bars (async jobs), served-area/peak KPIs, ROI (payback months + 5-yr net from revenue input), one-click executive PDF |

## 5. Monetization infrastructure

- **PDF engine** (`services/saas/report.py`, ReportLab): white-label logo,
  link-budget matrix (incl. foliage/rain/gas/MIMO lines), PIL-rendered
  terrain profile chart (provenance-colored), coverage heatmap, per-site
  BOM with CAPEX/OPEX/5-yr TCO. `POST /api/saas/report.pdf`.
- **Cost engine** (`services/saas/costs.py`): per-technology BOMs
  (macro, CBRS, 5G n77, Wi-Fi, PtP, TETRA, LoRa) with OPEX fractions.
- **Async jobs** (`services/saas/jobs.py`): `POST /api/saas/coverage/async`
  → job id; the engine reports per-radial progress; `GET /api/saas/jobs/{id}`
  drives the UI progress bar; results persist to disk for cross-worker polls.
- **Audit trail**: register/login/tier-change/API-token/PDF/coverage events.

## 6. Frictionless onboarding

- Drag-and-drop DXF upload zone.
- **Auto-detected georeferencing hints** on upload: UTM-magnitude
  coordinates → suggest *known CRS* mode; elevation statistics → suggest
  feet vs meters (pre-fills the wizard, shown as an editable suggestion).
- Inline glossary tooltips (ⓘ) for Fresnel, FSPL, k-factor, fade margin,
  downtilt, Deygout, sensitivity and Helmert residuals.

## 7. API surface added (all under OpenAPI tag `saas`)

```
POST /api/auth/register | login | tier | api-token | logo    GET /api/auth/me | tiers | audit
POST /api/projects  GET /api/projects[/{id}] PUT/DELETE /api/projects/{id}
POST /api/projects/{id}/duplicate | share    GET /api/projects/shared/{token}
GET  /api/saas/costs    POST /api/saas/report.pdf
POST /api/saas/coverage/async    GET /api/saas/jobs/{job_id}
```

## 8. Security posture (implemented)

- Passwords: PBKDF2-HMAC-SHA256, 200k iterations, per-user salt,
  constant-time compare. Login lockout: 8 failures / 15 min per account.
- Tokens: 32-byte opaque bearers; session tokens expire after 30 days;
  `POST /api/auth/logout` revokes; API tokens (Enterprise) are long-lived
  but revocable. Tokens never appear in the audit log.
- Tier changes: self-serve only in open mode; in SaaS mode
  (`AM_SAAS_MODE=1`) they require the `X-Billing-Secret` header matching
  `AM_BILLING_SECRET` — the stand-in for the billing provider's webhook.
- Audit log: tenant-scoped in SaaS mode (a manager sees only their org).
- Resource ownership: authenticated DXF uploads and antenna patterns are
  bound to the uploader (mutations 403 for other accounts; antenna listings
  are owner-filtered). Project access is strictly owner-checked; shared
  links are unguessable capability tokens and never echo the token back.
- DoS bounds: 4 concurrent background simulations (429 beyond), Pydantic
  resolution caps on every sim, upload size caps, LRU-bounded caches.

## 9. Production notes

Swap SQLite → PostgreSQL by replacing `_conn()`; wire the billing provider
(Stripe) webhook to `POST /api/auth/tier` with the shared secret; add
per-user disk quotas and per-IP rate limiting at the reverse proxy.
