"""GDPR subject access (art. 15/20), erasure (art. 17) and audit retention.

These are compliance obligations, not features: a customer's DPO signs off on
the platform partly on the strength of "we can hand a user their data and we
can delete them". Before this suite there was no delete path at all — closing
an account meant asking an operator to run SQL — and the audit table grew
without limit, so a deployment quietly accumulated years of emails and client
IPs with no stated retention.
"""
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services import results_store
from app.services.dxf.store import get_dxf_store
from app.services.saas import db, gdpr
from app.services.terrain.fusion import TerrainFusionService

PASSWORD = "hunter22secure"


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


def _register(client, org=""):
    email = f"gdpr{time.time_ns()}@x.io"
    r = client.post("/api/auth/register", json={
        "email": email, "password": PASSWORD, "name": "Data Subject",
        "role": "manager", "org_name": org})
    assert r.status_code == 200, r.text
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}, body["user"]


# ------------------------------------------------------------------ access
def test_export_hands_the_user_their_own_data_and_nobody_elses(client):
    """Art. 15: on request, everything held about the subject."""
    other_hdrs, other = _register(client)
    client.post("/api/projects", json={"name": "Their secret site",
                                       "kind": "coverage", "data": {"a": 1}},
                headers=other_hdrs)

    hdrs, user = _register(client)
    client.post("/api/projects", json={"name": "My site", "kind": "coverage",
                                       "data": {"tx_lat": 47.0}},
                headers=hdrs)

    dump = client.get("/api/auth/export", headers=hdrs)
    assert dump.status_code == 200, dump.text
    body = dump.json()

    assert body["account"]["email"] == user["email"]
    names = [p["name"] for p in body["projects"]]
    assert names == ["My site"]
    # The study payload comes out too — this doubles as a portable backup.
    assert body["projects"][0]["data"] == {"tx_lat": 47.0}
    # Their own activity, and only theirs.
    assert any(a["action"] == "project_create" for a in body["audit"])
    assert other["email"] not in dump.text
    assert "Their secret site" not in dump.text
    # No password material ever leaves the server.
    assert "password_hash" not in dump.text


def test_export_requires_authentication(client):
    assert client.get("/api/auth/export").status_code == 401


# ----------------------------------------------------------------- erasure
def test_erasure_destroys_the_account_and_everything_it_owns(client, tmp_path):
    hdrs, user = _register(client)
    uid = user["id"]
    proj = client.post("/api/projects", json={"name": "Doomed",
                                              "kind": "coverage", "data": {}},
                       headers=hdrs).json()["project"]

    # An owner-tagged raster and an owner-tagged antenna pattern: the account
    # row is the *small* part of what erasure has to reach.
    results_store.save("coverage", "deadbeef99", b"\x89PNG-not-really",
                       {"owner_id": uid, "kind": "coverage"})
    png_path, meta_path = results_store._paths("deadbeef99", "coverage")
    assert png_path.exists()
    gdpr.ANTENNA_DIR.mkdir(parents=True, exist_ok=True)
    ant = gdpr.ANTENNA_DIR / f"pat{uid}.json"
    ant.write_text('{"name": "Private pattern", "owner_id": %d}' % uid)
    # An uploaded site drawing is the most sensitive thing here: a customer's
    # floor plan. It is owner-tagged on a sidecar, not in the database.
    session = get_dxf_store().create("site.dxf", b"0\nSECTION\n0\nEOF\n",
                                     owner_id=uid)
    session.persist_state()
    dxf_path = session.path
    assert dxf_path.exists()

    r = client.request("DELETE", "/api/auth/account", headers=hdrs,
                       json={"password": PASSWORD, "confirm": "DELETE"})
    assert r.status_code == 200, r.text
    erased = r.json()["erased"]
    assert erased["projects"] == 1 and erased["results"] == 1
    assert erased["antennas"] == 1 and erased["dxf"] == 1

    # The account is gone: the session token no longer resolves, and the
    # credentials no longer authenticate.
    assert client.get("/api/auth/me", headers=hdrs).status_code == 401
    assert client.post("/api/auth/login", json={
        "email": user["email"], "password": PASSWORD}).status_code == 401
    assert db.get_user_by_email(user["email"]) is None
    assert db.get_project(proj["id"]) is None
    # ...and so are the artefacts, on disk, not merely hidden behind a guard.
    assert not png_path.exists() and not meta_path.exists()
    assert not ant.exists()
    assert not dxf_path.exists()
    assert not dxf_path.with_suffix(".state.json").exists()
    # The hot cache must not keep serving a raster whose file was unlinked.
    assert results_store.load("coverage", "deadbeef99") is None


def test_erasure_is_reauthenticated(client):
    """A bearer token is what an unlocked laptop hands over; it must not be
    enough on its own to destroy someone's account."""
    hdrs, user = _register(client)

    wrong = client.request("DELETE", "/api/auth/account", headers=hdrs,
                           json={"password": "not-the-password",
                                 "confirm": "DELETE"})
    assert wrong.status_code == 401
    # An accidental fetch without the typed confirmation is a 422, not a wipe.
    unconfirmed = client.request("DELETE", "/api/auth/account", headers=hdrs,
                                 json={"password": PASSWORD, "confirm": "yes"})
    assert unconfirmed.status_code == 422
    assert db.get_user_by_email(user["email"]) is not None


def test_erasure_pseudonymises_rather_than_deletes_the_audit_trail(client):
    """Art. 17 vs. the operator's duty to evidence who changed a site.

    The actions survive so the trail stays coherent; the identification does
    not. A row that still carried the email or the client IP would make the
    "erasure" cosmetic.
    """
    hdrs, user = _register(client)
    client.post("/api/projects", json={"name": "Traced", "kind": "coverage",
                                       "data": {}}, headers=hdrs)
    uid = user["id"]
    before = db.list_audit_for_user(uid)
    assert before, "the account should have produced audit rows"

    r = client.request("DELETE", "/api/auth/account", headers=hdrs,
                       json={"password": PASSWORD, "confirm": "DELETE"})
    subject = r.json()["erased"]["subject"]
    assert subject and subject.startswith("erased-")

    with sqlite3.connect(db.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM audit_log WHERE subject=?",
                         (subject,)).fetchall()
    assert len(rows) >= len(before)
    for row in rows:
        assert row["user_id"] is None
        assert row["ip"] is None
    # The actions themselves are still there.
    assert {r["action"] for r in rows} >= {"register", "project_create"}
    # And nothing anywhere still names the person.
    everything = db.list_audit(limit=1000)
    assert all(a.get("email") != user["email"] for a in everything)


def test_erasure_is_itself_audited_without_naming_the_subject(client):
    hdrs, user = _register(client)
    r = client.request("DELETE", "/api/auth/account", headers=hdrs,
                       json={"password": PASSWORD, "confirm": "DELETE"})
    subject = r.json()["erased"]["subject"]
    with sqlite3.connect(db.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT * FROM audit_log WHERE subject=? AND "
                        "action='account_erase'", (subject,)).fetchone()
    assert row is not None, "an erasure must leave a record that it happened"
    assert row["user_id"] is None and row["ip"] is None
    assert "projects=" in row["detail"]


def test_an_erased_actor_stays_in_its_own_organisations_trail(client,
                                                              monkeypatch):
    """The tenant-scoped audit view joins users to get the org. An erased
    account has no user row left, so without the org stamped on the rows the
    whole history would silently vanish from the manager's view — the trail
    would be destroyed by the erasure, not just de-identified."""
    monkeypatch.setenv("AM_SAAS_MODE", "1")
    org = f"Org{time.time_ns()}"
    hdrs, user = _register(client, org=org)
    client.post("/api/projects", json={"name": "Audited", "kind": "coverage",
                                       "data": {}}, headers=hdrs)
    # A second manager for the same tenant reads the trail afterwards.
    r = client.request("DELETE", "/api/auth/account", headers=hdrs,
                       json={"password": PASSWORD, "confirm": "DELETE"})
    subject = r.json()["erased"]["subject"]

    entries = db.list_audit(limit=1000, org_name=org)
    subjects = {e.get("subject") for e in entries}
    assert subject in subjects
    assert {e["action"] for e in entries} >= {"project_create", "account_erase"}
    assert all(e.get("email") != user["email"] for e in entries)


# --------------------------------------------------------------- retention
def test_audit_rows_expire_on_the_stated_retention(client, monkeypatch):
    """Art. 5(1)(e): audit rows carry emails and client IPs, so "keep
    forever" is not a policy. Nothing pruned them before."""
    monkeypatch.setenv("AM_AUDIT_RETENTION_DAYS", "30")
    stale = time.time() - 400 * 86_400
    with sqlite3.connect(db.DB_PATH) as c:
        c.execute("INSERT INTO audit_log (user_id, action, detail, ts) "
                  "VALUES (NULL, 'ancient_probe', '', ?)", (stale,))
        c.commit()

    def count():
        with sqlite3.connect(db.DB_PATH) as c:
            return c.execute("SELECT COUNT(*) FROM audit_log WHERE "
                             "action='ancient_probe'").fetchone()[0]

    assert count() == 1
    assert db.prune_audit() >= 1
    assert count() == 0


def test_retention_can_be_disabled_for_archival_deployments(monkeypatch):
    """Air-gapped installs that archive out of band must be able to opt out —
    a silent delete of a regulator-mandated trail would be worse than the
    unbounded growth it replaces."""
    monkeypatch.setenv("AM_AUDIT_RETENTION_DAYS", "0")
    stale = time.time() - 4000 * 86_400
    with sqlite3.connect(db.DB_PATH) as c:
        c.execute("INSERT INTO audit_log (user_id, action, detail, ts) "
                  "VALUES (NULL, 'kept_probe', '', ?)", (stale,))
        c.commit()
    assert db.prune_audit() == 0
    with sqlite3.connect(db.DB_PATH) as c:
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE "
                         "action='kept_probe'").fetchone()[0] == 1
        c.execute("DELETE FROM audit_log WHERE action='kept_probe'")
        c.commit()
