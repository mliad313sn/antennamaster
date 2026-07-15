"""Tests for the centralized audit-log middleware (OT/IT compliance):
critical actions recorded with user id + client IP, to file and DB."""
import time

import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.saas import db
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


def _register(client, ip=None):
    hdrs = {"X-Forwarded-For": ip} if ip else {}
    r = client.post("/api/auth/register", json={
        "email": f"aud{time.time_ns()}@x.io", "password": "hunter22secure",
        "role": "manager", "org_name": f"Org{time.time_ns()}"}, headers=hdrs)
    return r.json(), {"Authorization": f"Bearer {r.json()['token']}"}


def test_register_and_export_are_audited_with_ip(client):
    body, hdrs = _register(client, ip="203.0.113.42, 10.0.0.1")
    uid = body["user"]["id"]
    # A critical export carrying the bearer token → middleware resolves user.
    hdrs2 = {**hdrs, "X-Forwarded-For": "198.51.100.9"}
    r = client.get("/api/terrain/profile.kml", params={
        "lat1": 47.0, "lon1": 15.0, "lat2": 47.05, "lon2": 15.08,
        "samples": 16}, headers=hdrs2)
    assert r.status_code == 200

    rows = [a for a in db.list_audit(limit=50) if a["user_id"] == uid]
    by_action = {a["action"]: a for a in rows}
    # Register recorded with the first-hop client IP (not the proxy hop).
    assert "register" in by_action
    assert by_action["register"]["ip"] == "203.0.113.42"
    # Export recorded, attributed to the token's user, with its IP.
    assert "export_kml" in by_action
    assert by_action["export_kml"]["ip"] == "198.51.100.9"


def test_noncritical_request_not_audited(client):
    body, hdrs = _register(client)
    uid = body["user"]["id"]
    before = len([a for a in db.list_audit(limit=100) if a["user_id"] == uid])
    # A read that isn't a critical action must not create an audit row.
    client.get("/api/rf/technologies", headers=hdrs)
    client.get("/api/rf/models", headers=hdrs)
    after = len([a for a in db.list_audit(limit=100) if a["user_id"] == uid])
    assert after == before


def test_failed_login_is_not_recorded_as_success(client):
    body, _ = _register(client)
    email = body["user"]["email"]
    # Wrong password → 401 → middleware skips (records only status < 400).
    r = client.post("/api/auth/login",
                    json={"email": email, "password": "wrongwrong9"})
    assert r.status_code == 401
    logins = [a for a in db.list_audit(limit=50)
              if a["action"] == "login" and a.get("email") == email]
    assert logins == []


def test_audit_log_file_written(client):
    from app.config import DATA_DIR
    _register(client)
    path = DATA_DIR / "audit.log"
    assert path.exists()
    # Owner-only permissions on the audit trail (POSIX systems).
    import os
    if hasattr(os, "getuid"):
        assert (path.stat().st_mode & 0o077) == 0
