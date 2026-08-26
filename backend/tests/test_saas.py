"""SaaS layer: auth, tiers/entitlements, projects, jobs, PDF, costs, hints."""
import time

import ezdxf
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


def _register(client, email, role="field", tier=None):
    r = client.post("/api/auth/register", json={
        "email": email, "password": "hunter22secure", "role": role,
        "name": "Test", "org_name": "ACME Mining"})
    assert r.status_code == 200, r.text
    body = r.json()
    hdrs = {"Authorization": f"Bearer {body['token']}"}
    if tier:
        client.post("/api/auth/tier", json={"tier": tier}, headers=hdrs)
    return hdrs, body["user"]


# ---------------------------------------------------------------- auth
def test_register_login_me(client):
    hdrs, user = _register(client, f"a{time.time_ns()}@x.io", role="manager")
    assert user["role"] == "manager" and user["tier"] == "basic"
    me = client.get("/api/auth/me", headers=hdrs)
    assert me.status_code == 200
    # Wrong password rejected.
    bad = client.post("/api/auth/login", json={
        "email": user["email"], "password": "wrongwrong1"})
    assert bad.status_code == 401
    # Tier matrix is public.
    tiers = client.get("/api/auth/tiers").json()["tiers"]
    assert [t["key"] for t in tiers] == ["basic", "pro", "enterprise"]


# ------------------------------------------------------- tier enforcement
def test_tier_gating_for_logged_in_users(client, site_dxf):
    hdrs, _ = _register(client, f"b{time.time_ns()}@x.io")   # basic tier
    with open(site_dxf, "rb") as fh:
        dxf_id = client.post("/api/dxf/upload",
                             files={"file": ("s.dxf", fh, "application/dxf")}
                             ).json()["dxf_id"]
    georef_body = {"mode": "origin_bearing", "layers": ["SURVEY_POINTS"],
                   "origin_lat": 47.0, "origin_lon": 15.0}
    # Basic user: DXF fusion is a Pro feature -> 402.
    r = client.post(f"/api/dxf/{dxf_id}/georeference", json=georef_body,
                    headers=hdrs)
    assert r.status_code == 402
    # Private preset gated to enterprise.
    r = client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "private_nr_n77",
        "radius_km": 2, "n_radials": 36, "n_steps": 20}, headers=hdrs)
    assert r.status_code == 402
    # Upgrade to pro: fusion unlocks, private still locked.
    client.post("/api/auth/tier", json={"tier": "pro"}, headers=hdrs)
    assert client.post(f"/api/dxf/{dxf_id}/georeference", json=georef_body,
                       headers=hdrs).status_code == 200
    # Enterprise unlocks everything.
    client.post("/api/auth/tier", json={"tier": "enterprise"}, headers=hdrs)
    r = client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "private_nr_n77",
        "radius_km": 2, "n_radials": 36, "n_steps": 20}, headers=hdrs)
    assert r.status_code == 200
    # API tokens are enterprise-only (now allowed).
    assert client.post("/api/auth/api-token", headers=hdrs).status_code == 200


def test_anonymous_open_mode_unrestricted(client, site_dxf):
    """Self-hosted open mode: no token -> no gating (backwards compatible)."""
    with open(site_dxf, "rb") as fh:
        dxf_id = client.post("/api/dxf/upload",
                             files={"file": ("s.dxf", fh, "application/dxf")}
                             ).json()["dxf_id"]
    r = client.post(f"/api/dxf/{dxf_id}/georeference", json={
        "mode": "origin_bearing", "layers": ["SURVEY_POINTS"],
        "origin_lat": 47.0, "origin_lon": 15.0})
    assert r.status_code == 200


def test_saas_mode_gates_anonymous(client, site_dxf, monkeypatch):
    monkeypatch.setenv("AM_SAAS_MODE", "1")
    with open(site_dxf, "rb") as fh:
        dxf_id = client.post("/api/dxf/upload",
                             files={"file": ("s.dxf", fh, "application/dxf")}
                             ).json()["dxf_id"]
    r = client.post(f"/api/dxf/{dxf_id}/georeference", json={
        "mode": "origin_bearing", "layers": ["SURVEY_POINTS"],
        "origin_lat": 47.0, "origin_lon": 15.0})
    assert r.status_code == 402


# --------------------------------------------------------------- projects
def test_project_crud_quota_share(client):
    hdrs, _ = _register(client, f"c{time.time_ns()}@x.io")   # basic: 3 max
    ids = []
    for i in range(3):
        r = client.post("/api/projects", json={
            "name": f"Site {i}", "data": {"tx": {"lat": 47, "lng": 15}}},
            headers=hdrs)
        assert r.status_code == 200
        ids.append(r.json()["project"]["id"])
    # Quota hit on the 4th.
    assert client.post("/api/projects", json={"name": "over"},
                       headers=hdrs).status_code == 402
    assert len(client.get("/api/projects", headers=hdrs).json()["projects"]) == 3
    # Update + share + anonymous shared read.
    client.put(f"/api/projects/{ids[0]}", json={"name": "Renamed"}, headers=hdrs)
    token = client.post(f"/api/projects/{ids[0]}/share",
                        headers=hdrs).json()["share_token"]
    shared = client.get(f"/api/projects/shared/{token}")
    assert shared.status_code == 200
    assert shared.json()["project"]["name"] == "Renamed"
    # Delete frees quota; duplicate works.
    client.delete(f"/api/projects/{ids[2]}", headers=hdrs)
    assert client.post(f"/api/projects/{ids[0]}/duplicate",
                       headers=hdrs).status_code == 200
    # Other users cannot read my project.
    hdrs2, _ = _register(client, f"d{time.time_ns()}@x.io")
    assert client.get(f"/api/projects/{ids[0]}", headers=hdrs2).status_code == 404


# ------------------------------------------------------------ jobs & costs
def test_async_coverage_job(client):
    r = client.post("/api/saas/coverage/async", json={
        "lat": 47.0, "lon": 15.0, "technology": "gsm900",
        "radius_km": 4, "n_radials": 48, "n_steps": 30})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    for _ in range(100):
        job = client.get(f"/api/saas/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    assert job["progress"] == 1.0
    assert job["result"]["png_url"].startswith("/api/rf/coverage/")


def test_cost_estimator(client):
    est = client.get("/api/saas/costs",
                     params={"technology": "private_nr_n77", "sites": 4}).json()
    assert est["capex_total_usd"] == pytest.approx(est["capex_per_site_usd"] * 4)
    assert est["tco_5y_usd"] > est["capex_total_usd"]
    assert len(est["bom_per_site"]) >= 3


# ----------------------------------------------------------------- PDF
def test_pdf_report(client):
    r = client.post("/api/saas/report.pdf", json={
        "title": "ACME Quarry Private 5G",
        "lat1": 47.0, "lon1": 14.95, "lat2": 47.0, "lon2": 15.05,
        "technology": "gsm900", "sites": 2})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    # PDFs compress flat-color charts hard; presence check instead of size.
    assert len(r.content) > 5_000
    assert b"/Image" in r.content             # embedded profile chart


def test_report_figures_come_from_the_engine_not_the_request(client):
    """A signed deliverable must never print a number the caller supplied.

    Regression: report.pdf used to take served_area_fraction and
    max_rx_power_dbm straight off the request body and print them beside a
    map rendered from the stored raster, so a client could claim 99% coverage
    on a map showing far less.  The fields are now rejected outright and the
    figures are read from the stored study.
    """
    # 1) The fabrication vector is closed: the removed fields are refused.
    bad = client.post("/api/saas/report.pdf", json={
        "title": "Fabricated", "technology": "gsm900",
        "served_area_fraction": 0.99, "max_rx_power_dbm": -10.0})
    assert bad.status_code == 422, "caller-supplied statistics must be rejected"

    # 2) A real coverage run stores the engine's own figures...
    cov = client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "gsm900", "radius_km": 4,
        "n_radials": 36, "n_steps": 20})
    assert cov.status_code == 200
    body = cov.json()
    cid = body["coverage_id"]
    engine_served = body["stats"]["served_area_fraction"]

    from app.services import results_store
    stored = results_store.load("coverage", cid)
    assert stored is not None
    assert stored[1]["stats"]["served_area_fraction"] == pytest.approx(engine_served)

    # 3) ...and the PDF renders from that stored record.
    r = client.post("/api/saas/report.pdf", json={
        "title": "Honest", "technology": "gsm900", "coverage_id": cid})
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"


def test_audit_log_manager_only(client):
    hdrs_f, _ = _register(client, f"e{time.time_ns()}@x.io", role="field")
    assert client.get("/api/auth/audit", headers=hdrs_f).status_code == 403
    hdrs_m, _ = _register(client, f"f{time.time_ns()}@x.io", role="manager")
    entries = client.get("/api/auth/audit", headers=hdrs_m).json()["entries"]
    assert any(e["action"] == "register" for e in entries)


# --------------------------------------------------------- onboarding hints
def test_georef_hints(client, tmp_path):
    # UTM-magnitude drawing in feet-like elevations.
    doc = ezdxf.new("R2010")
    doc.layers.add("PTS")
    msp = doc.modelspace()
    for i in range(12):
        msp.add_point((500_000 + i * 30, 5_200_000 + i * 30, 6800 + i),
                      dxfattribs={"layer": "PTS"})
    p = tmp_path / "utm.dxf"
    doc.saveas(p)
    with open(p, "rb") as fh:
        hints = client.post("/api/dxf/upload",
                            files={"file": ("utm.dxf", fh, "application/dxf")}
                            ).json()["georef_hints"]
    assert hints["suggested_mode"] == "known_crs"
    assert hints["suggested_unit"] == "ft"
