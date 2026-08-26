"""Regression tests for the security-audit fixes."""
import time

import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


def _register(client, email, role="field", org="Org A"):
    r = client.post("/api/auth/register", json={
        "email": email, "password": "hunter22secure", "role": role,
        "org_name": org})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_tenancy_cannot_be_joined_by_asserting_an_org_name(client, monkeypatch):
    """A tenant is not a string the caller supplies.

    Exploit this closes: the audit log is scoped on `users.org_name`, and BOTH
    that string and `role` were accepted verbatim from the registration body.
    An attacker who reads a customer's organisation name off any exported PDF
    (it is printed on the report header) could register as
    role="manager", org_name="<that org>" and read the tenant's entire audit
    log - every employee email, client IP and action.  SECURITY_COMPLIANCE.md
    and the endpoint's own docstring promise the exact opposite.
    """
    monkeypatch.setenv("AM_SAAS_MODE", "1")
    victim_org = f"AcmeTelecom{time.time_ns()}"
    victim_email = f"victim{time.time_ns()}@acme.example"
    victim = _register(client, victim_email, role="manager", org=victim_org)
    # The victim's own manager can see their own org's activity.
    own = client.get("/api/auth/audit", headers=victim)
    assert own.status_code == 200
    assert any(victim_email == e.get("email") for e in own.json()["entries"])

    # The attacker knows only the org NAME and claims to be its manager.
    attack = client.post("/api/auth/register", json={
        "email": f"mallory{time.time_ns()}@evil.example",
        "password": "hunter22secure", "role": "manager",
        "org_name": victim_org})
    if attack.status_code == 200:
        # If registration is allowed at all, it must not confer tenancy.
        hdrs = {"Authorization": f"Bearer {attack.json()['token']}"}
        leaked = client.get("/api/auth/audit", headers=hdrs)
        entries = leaked.json().get("entries", []) if leaked.status_code == 200 else []
        assert not any(e.get("email") == victim_email for e in entries), (
            "cross-tenant audit disclosure: attacker read the victim's log")
    else:
        # Preferred: claiming an existing organisation is refused outright.
        assert attack.status_code == 409, attack.text


def test_validation_errors_never_echo_the_submitted_value(client):
    """A 422 must not reflect what was sent.

    Regression: FastAPI's default handler puts the rejected value in an
    `input` field, so registering with a too-short password answered with
    that plaintext password - straight into browser devtools, reverse-proxy
    logs and any client-side error reporter.
    """
    secret = "hunter2"                      # 7 chars: fails min_length=8
    r = client.post("/api/auth/register",
                    json={"email": "leak@x.io", "password": secret})
    assert r.status_code == 422
    assert secret not in r.text, "422 echoed the submitted password"
    # The client still gets what it needs to fix the call.
    err = r.json()["detail"][0]
    assert err["loc"] == ["body", "password"]
    assert "8 characters" in err["msg"]
    assert "input" not in err and "ctx" not in err

    # Not just passwords - no rejected value is reflected, whatever the field.
    r2 = client.post("/api/rf/coverage", json={
        "lat": 999.0, "lon": 15.0, "technology": "gsm900"})
    assert r2.status_code == 422
    assert "999" not in r2.text


def test_coverage_results_are_owner_scoped(client):
    """A coverage id is not a bearer capability.

    Result ids travel in share links, exported PDF footers, audit detail
    fields and reverse-proxy logs.  The .png/.tif/.kmz endpoints and the /at
    point query took no user dependency at all, so anyone holding a 12-hex id
    could pull another tenant's georeferenced site footprint - confidential
    infrastructure locations for operators, mines and public-safety networks.
    """
    owner = _register(client, f"cov{time.time_ns()}@x.io")
    run = client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "gsm900", "radius_km": 4,
        "n_radials": 36, "n_steps": 20}, headers=owner)
    assert run.status_code == 200, run.text
    cid = run.json()["coverage_id"]

    # The owner reads every representation.
    for path in (f"/api/rf/coverage/{cid}.png", f"/api/rf/coverage/{cid}.tif",
                 f"/api/rf/coverage/{cid}.kmz"):
        assert client.get(path, headers=owner).status_code == 200, path
    assert client.get(f"/api/rf/coverage/{cid}/at",
                      params={"lat": 47.0, "lon": 15.0},
                      headers=owner).status_code == 200

    # A stranger holding the id gets 404 - not 403, so the id is not an
    # existence oracle - on every representation, including anonymously.
    other = _register(client, f"cx{time.time_ns()}@x.io")
    for hdrs in (other, None):
        for path in (f"/api/rf/coverage/{cid}.png",
                     f"/api/rf/coverage/{cid}.tif",
                     f"/api/rf/coverage/{cid}.kmz"):
            r = client.get(path, headers=hdrs) if hdrs else client.get(path)
            assert r.status_code == 404, f"{path} leaked to a non-owner"
        at = f"/api/rf/coverage/{cid}/at"
        r = (client.get(at, params={"lat": 47.0, "lon": 15.0}, headers=hdrs)
             if hdrs else client.get(at, params={"lat": 47.0, "lon": 15.0}))
        assert r.status_code == 404, "point query leaked to a non-owner"


def test_anonymous_coverage_stays_open_for_self_hosting(client):
    """Owner-scoping must not break the anonymous single-tenant deployment:
    a result with no owner stays readable, exactly like an anonymous DXF."""
    run = client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "gsm900", "radius_km": 4,
        "n_radials": 36, "n_steps": 20})
    assert run.status_code == 200
    cid = run.json()["coverage_id"]
    assert client.get(f"/api/rf/coverage/{cid}.png").status_code == 200


def test_saas_mode_blocks_self_serve_tier_escalation(client, monkeypatch):
    hdrs = _register(client, f"esc{time.time_ns()}@x.io")
    monkeypatch.setenv("AM_SAAS_MODE", "1")
    monkeypatch.setenv("AM_BILLING_SECRET", "topsecret")
    # Client alone cannot upgrade.
    r = client.post("/api/auth/tier", json={"tier": "enterprise"}, headers=hdrs)
    assert r.status_code == 403
    # The billing webhook (with the shared secret) can.
    r = client.post("/api/auth/tier", json={"tier": "enterprise"},
                    headers={**hdrs, "X-Billing-Secret": "topsecret"})
    assert r.status_code == 200
    assert r.json()["user"]["tier"] == "enterprise"


def test_audit_is_org_scoped_in_saas_mode(client, monkeypatch):
    suffix = time.time_ns()
    hdrs_a = _register(client, f"mgr{suffix}@a.io", role="manager", org=f"OrgA{suffix}")
    _register(client, f"user{suffix}@b.io", role="field", org=f"OrgB{suffix}")
    monkeypatch.setenv("AM_SAAS_MODE", "1")
    entries = client.get("/api/auth/audit", headers=hdrs_a).json()["entries"]
    emails = {e["email"] for e in entries}
    assert f"mgr{suffix}@a.io" in emails            # own org visible
    assert f"user{suffix}@b.io" not in emails       # other tenant invisible


def test_logout_revokes_token(client):
    hdrs = _register(client, f"out{time.time_ns()}@x.io")
    assert client.get("/api/auth/me", headers=hdrs).status_code == 200
    client.post("/api/auth/logout", headers=hdrs)
    assert client.get("/api/auth/me", headers=hdrs).status_code == 401


def test_login_lockout_after_failures(client):
    email = f"lock{time.time_ns()}@x.io"
    _register(client, email)
    for _ in range(8):
        client.post("/api/auth/login",
                    json={"email": email, "password": "wrongwrong1"})
    r = client.post("/api/auth/login",
                    json={"email": email, "password": "hunter22secure"})
    assert r.status_code == 429                     # locked even with correct pw


def test_dxf_ownership_blocks_other_accounts(client, site_dxf):
    hdrs_owner = _register(client, f"own{time.time_ns()}@x.io")
    client.post("/api/auth/tier", json={"tier": "pro"}, headers=hdrs_owner)
    with open(site_dxf, "rb") as fh:
        dxf_id = client.post("/api/dxf/upload",
                             files={"file": ("s.dxf", fh, "application/dxf")},
                             headers=hdrs_owner).json()["dxf_id"]
    hdrs_other = _register(client, f"oth{time.time_ns()}@x.io")
    client.post("/api/auth/tier", json={"tier": "pro"}, headers=hdrs_other)
    body = {"mode": "origin_bearing", "layers": ["SURVEY_POINTS"],
            "origin_lat": 47.0, "origin_lon": 15.0}
    # Another account can neither re-georeference nor delete.
    assert client.post(f"/api/dxf/{dxf_id}/georeference", json=body,
                       headers=hdrs_other).status_code == 403
    assert client.delete(f"/api/dxf/{dxf_id}",
                         headers=hdrs_other).status_code == 403
    # The owner can.
    assert client.post(f"/api/dxf/{dxf_id}/georeference", json=body,
                       headers=hdrs_owner).status_code == 200


def test_antenna_listing_is_owner_scoped(client):
    msi = ("NAME PRIVATE-ANT\nGAIN 15 dBi\nHORIZONTAL 360\n"
           + "\n".join(f"{a} 1.0" for a in range(360))
           + "\nVERTICAL 360\n" + "\n".join(f"{a} 1.0" for a in range(360)))
    hdrs_a = _register(client, f"anta{time.time_ns()}@x.io")
    up = client.post("/api/rf/antenna",
                     files={"file": ("p.msi", msi.encode(), "text/plain")},
                     headers=hdrs_a)
    assert up.status_code == 200
    aid = up.json()["antenna_id"]
    mine = {a["antenna_id"] for a in
            client.get("/api/rf/antennas", headers=hdrs_a).json()["antennas"]}
    assert aid in mine
    hdrs_b = _register(client, f"antb{time.time_ns()}@x.io")
    theirs = {a["antenna_id"] for a in
              client.get("/api/rf/antennas", headers=hdrs_b).json()["antennas"]}
    assert aid not in theirs


def test_shared_project_does_not_echo_token(client):
    hdrs = _register(client, f"shr{time.time_ns()}@x.io")
    pid = client.post("/api/projects", json={"name": "S", "data": {}},
                      headers=hdrs).json()["project"]["id"]
    token = client.post(f"/api/projects/{pid}/share",
                        headers=hdrs).json()["share_token"]
    shared = client.get(f"/api/projects/shared/{token}").json()["project"]
    assert "share_token" not in shared and "user_id" not in shared


def test_dxf_fusion_gated_on_terrain_endpoints_in_saas_mode(client, site_dxf,
                                                            monkeypatch):
    # Georeference in open mode first (anonymous).
    with open(site_dxf, "rb") as fh:
        dxf_id = client.post("/api/dxf/upload",
                             files={"file": ("s.dxf", fh, "application/dxf")}
                             ).json()["dxf_id"]
    client.post(f"/api/dxf/{dxf_id}/georeference", json={
        "mode": "origin_bearing", "layers": ["SURVEY_POINTS"],
        "origin_lat": 47.0, "origin_lon": 15.0})
    monkeypatch.setenv("AM_SAAS_MODE", "1")
    # Anonymous fused profile/elevation now requires the Pro feature.
    assert client.get("/api/terrain/profile", params={
        "lat1": 47.0, "lon1": 14.99, "lat2": 47.005, "lon2": 15.005,
        "samples": 32, "dxf_id": dxf_id}).status_code == 402
    assert client.get("/api/terrain/elevation", params={
        "lat": 47.0, "lon": 15.0, "dxf_id": dxf_id}).status_code == 402
    # Without the DXF the same endpoints stay open (basic SRTM).
    assert client.get("/api/terrain/profile", params={
        "lat1": 47.0, "lon1": 14.99, "lat2": 47.005, "lon2": 15.005,
        "samples": 32}).status_code == 200


# --------------------------- consumer-path authz (IDOR/tier-gate regressions)
def _owned_georef_dxf(client, site_dxf, hdrs):
    """Upload + georeference a DXF as an owning (Pro) account, return its id."""
    client.post("/api/auth/tier", json={"tier": "pro"}, headers=hdrs)
    with open(site_dxf, "rb") as fh:
        dxf_id = client.post("/api/dxf/upload",
                             files={"file": ("s.dxf", fh, "application/dxf")},
                             headers=hdrs).json()["dxf_id"]
    r = client.post(f"/api/dxf/{dxf_id}/georeference", json={
        "mode": "origin_bearing", "layers": ["SURVEY_POINTS"],
        "origin_lat": 47.0, "origin_lon": 15.0}, headers=hdrs)
    assert r.status_code == 200, r.text
    return dxf_id


def test_dxf_consumer_paths_enforce_ownership(client, site_dxf):
    """A DXF is readable only by its owner across EVERY consuming endpoint,
    not just georeference/delete."""
    hdrs_o = _register(client, f"cown{time.time_ns()}@x.io")
    dxf_id = _owned_georef_dxf(client, site_dxf, hdrs_o)
    hdrs_x = _register(client, f"cx{time.time_ns()}@x.io")
    client.post("/api/auth/tier", json={"tier": "enterprise"}, headers=hdrs_x)

    prof = {"lat1": 47.0, "lon1": 14.99, "lat2": 47.005, "lon2": 15.005,
            "samples": 32, "dxf_id": dxf_id}
    assert client.get("/api/terrain/profile", params=prof,
                      headers=hdrs_x).status_code == 403
    assert client.get("/api/terrain/elevation",
                      params={"lat": 47.0, "lon": 15.0, "dxf_id": dxf_id},
                      headers=hdrs_x).status_code == 403
    assert client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "gsm900", "radius_km": 4,
        "n_radials": 36, "n_steps": 20, "dxf_id": dxf_id},
        headers=hdrs_x).status_code == 403
    assert client.post("/api/indoor/coverage", json={
        "dxf_id": dxf_id, "layer_materials": {}, "tx_x": 0, "tx_y": 0},
        headers=hdrs_x).status_code == 403
    assert client.get(f"/api/indoor/{dxf_id}/preview.png",
                      headers=hdrs_x).status_code == 403
    # DXF-native read endpoints are owner-scoped too (regression guard: these
    # three previously skipped the owner check and leaked the terrain/footprint
    # to any account that knew the id).
    assert client.get(f"/api/dxf/{dxf_id}/layers",
                      headers=hdrs_x).status_code == 403
    assert client.get(f"/api/dxf/{dxf_id}/overlay.png",
                      headers=hdrs_x).status_code == 403
    assert client.get(f"/api/dxf/{dxf_id}/state",
                      headers=hdrs_x).status_code == 403
    # The owner still reaches them (200, or 422/409 for study reasons - never 403).
    assert client.get("/api/terrain/profile", params=prof,
                      headers=hdrs_o).status_code == 200
    assert client.get(f"/api/dxf/{dxf_id}/state",
                      headers=hdrs_o).status_code == 200
    assert client.get(f"/api/dxf/{dxf_id}/layers",
                      headers=hdrs_o).status_code == 200


def test_dxf_fusion_gate_on_coverage_in_saas_mode(client, site_dxf, monkeypatch):
    """/api/rf/coverage must apply the Pro dxf_fusion gate like the terrain
    endpoints - previously it skipped it (user never threaded through).

    Use an OWNERLESS DXF (uploaded anonymously in open mode) so the owner
    check passes and the tier gate is what we're actually exercising."""
    with open(site_dxf, "rb") as fh:
        dxf_id = client.post("/api/dxf/upload",
                             files={"file": ("s.dxf", fh, "application/dxf")}
                             ).json()["dxf_id"]
    client.post(f"/api/dxf/{dxf_id}/georeference", json={
        "mode": "origin_bearing", "layers": ["SURVEY_POINTS"],
        "origin_lat": 47.0, "origin_lon": 15.0})
    monkeypatch.setenv("AM_SAAS_MODE", "1")
    # Anonymous (basic) DXF-fused coverage is now blocked at the tier gate.
    assert client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "gsm900", "radius_km": 4,
        "n_radials": 36, "n_steps": 20, "dxf_id": dxf_id}).status_code == 402
    # Plain SRTM coverage stays open.
    assert client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "gsm900", "radius_km": 4,
        "n_radials": 36, "n_steps": 20}).status_code == 200


def test_antenna_load_is_owner_scoped(client):
    """A private pattern cannot be USED by another tenant (not just hidden
    from their list)."""
    msi = ("NAME SECRET-ANT\nGAIN 15 dBi\nHORIZONTAL 360\n"
           + "\n".join(f"{a} 1.0" for a in range(360))
           + "\nVERTICAL 360\n" + "\n".join(f"{a} 1.0" for a in range(360)))
    hdrs_a = _register(client, f"la{time.time_ns()}@x.io")
    aid = client.post("/api/rf/antenna",
                      files={"file": ("p.msi", msi.encode(), "text/plain")},
                      headers=hdrs_a).json()["antenna_id"]
    hdrs_b = _register(client, f"lb{time.time_ns()}@x.io")
    r = client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "gsm900", "radius_km": 4,
        "n_radials": 36, "n_steps": 20, "antenna_id": aid,
        "antenna_azimuth_deg": 90}, headers=hdrs_b)
    assert r.status_code == 403                    # cannot use another's pattern
    # The owner can.
    assert client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "gsm900", "radius_km": 4,
        "n_radials": 36, "n_steps": 20, "antenna_id": aid,
        "antenna_azimuth_deg": 90}, headers=hdrs_a).status_code == 200


def test_async_job_is_owner_scoped(client):
    """An account's async job result is not readable by another account or
    anonymously - job ids must not be a data-exfil oracle."""
    hdrs_a = _register(client, f"ja{time.time_ns()}@x.io")
    jid = client.post("/api/saas/coverage/async", json={
        "lat": 47.0, "lon": 15.0, "technology": "gsm900", "radius_km": 3,
        "n_radials": 36, "n_steps": 20}, headers=hdrs_a).json()["job_id"]
    # Owner sees it; a stranger and anonymous get 404 (not 403 - no oracle).
    assert client.get(f"/api/saas/jobs/{jid}", headers=hdrs_a).status_code == 200
    hdrs_b = _register(client, f"jb{time.time_ns()}@x.io")
    assert client.get(f"/api/saas/jobs/{jid}", headers=hdrs_b).status_code == 404
    assert client.get(f"/api/saas/jobs/{jid}").status_code == 404
    body = client.get(f"/api/saas/jobs/{jid}", headers=hdrs_a).json()
    assert "owner_id" not in body                  # internal field not leaked
