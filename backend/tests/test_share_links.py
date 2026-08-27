"""Share links are capabilities, so they must expire and be revocable.

A share link opens a saved study — site coordinates, customer name, the whole
design — to anyone holding the URL, with no login. It used to be minted once
and live forever, with no way to withdraw it: a link mailed to a client during
a tender still opened years later, and forwarding it to a competitor was
irreversible. The owner could not even see that a project was shared.
"""
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


def _account(client):
    r = client.post("/api/auth/register", json={
        "email": f"share{time.time_ns()}@x.io", "password": "hunter22secure",
        "role": "manager", "org_name": ""})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _project(client, hdrs):
    return client.post("/api/projects", json={
        "name": "Tender study", "kind": "coverage",
        "data": {"tx_lat": 47.0, "tx_lon": 15.0}}, headers=hdrs).json()["project"]


def test_a_new_link_expires_by_default(client):
    hdrs = _account(client)
    pid = _project(client, hdrs)["id"]

    r = client.post(f"/api/projects/{pid}/share", headers=hdrs)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["expires_at"] is not None
    # 30 days, give or take the second this test took to run.
    assert abs(body["expires_at"] - (time.time() + 30 * 86400)) < 60
    assert client.get(f"/api/projects/shared/{body['share_token']}").status_code == 200


def test_an_expired_link_stops_opening_and_is_not_an_oracle(client):
    hdrs = _account(client)
    pid = _project(client, hdrs)["id"]
    token = client.post(f"/api/projects/{pid}/share", headers=hdrs
                        ).json()["share_token"]

    # Walk the clock past the expiry rather than sleeping.
    with __import__("sqlite3").connect(db.DB_PATH) as c:
        c.execute("UPDATE projects SET share_expires_at=? WHERE id=?",
                  (time.time() - 1, pid))
        c.commit()

    dead = client.get(f"/api/projects/shared/{token}")
    assert dead.status_code == 404
    # Same answer as a token that never existed: an expired link must not
    # confirm that the project is there and used to be shared.
    unknown = client.get("/api/projects/shared/nosuchtokenatall")
    assert unknown.status_code == 404
    assert dead.json()["detail"] == unknown.json()["detail"]
    # The project itself is untouched for its owner.
    assert client.get(f"/api/projects/{pid}", headers=hdrs).status_code == 200


def test_a_link_can_be_revoked_immediately(client):
    hdrs = _account(client)
    pid = _project(client, hdrs)["id"]
    token = client.post(f"/api/projects/{pid}/share", headers=hdrs
                        ).json()["share_token"]
    assert client.get(f"/api/projects/shared/{token}").status_code == 200

    assert client.delete(f"/api/projects/{pid}/share",
                         headers=hdrs).status_code == 200
    # The forwarded copy is dead.
    assert client.get(f"/api/projects/shared/{token}").status_code == 404


def test_resharing_rotates_the_token_so_the_old_link_dies(client):
    """The only way to cut off a link already forwarded somewhere unintended
    is for a new share to invalidate the old one."""
    hdrs = _account(client)
    pid = _project(client, hdrs)["id"]
    first = client.post(f"/api/projects/{pid}/share", headers=hdrs
                        ).json()["share_token"]
    second = client.post(f"/api/projects/{pid}/share", headers=hdrs
                         ).json()["share_token"]
    assert first != second
    assert client.get(f"/api/projects/shared/{first}").status_code == 404
    assert client.get(f"/api/projects/shared/{second}").status_code == 200


def test_an_owner_may_opt_out_of_expiry_explicitly(client):
    hdrs = _account(client)
    pid = _project(client, hdrs)["id"]
    body = client.post(f"/api/projects/{pid}/share", headers=hdrs,
                       json={"expires_days": None}).json()
    assert body["expires_at"] is None
    assert client.get(f"/api/projects/shared/{body['share_token']}"
                      ).status_code == 200


def test_only_the_owner_may_share_or_revoke(client):
    hdrs = _account(client)
    other = _account(client)
    pid = _project(client, hdrs)["id"]
    token = client.post(f"/api/projects/{pid}/share", headers=hdrs
                        ).json()["share_token"]

    assert client.post(f"/api/projects/{pid}/share", headers=other
                       ).status_code == 404
    assert client.delete(f"/api/projects/{pid}/share", headers=other
                         ).status_code == 404
    # ...and the stranger's failed attempt did not revoke anything.
    assert client.get(f"/api/projects/shared/{token}").status_code == 200


def test_revocation_is_audited_as_a_revocation_not_a_deletion(client):
    """`DELETE /api/projects/{id}/share` matches the project_delete rule's
    substring too. A compliance log that reports a share withdrawal as a
    project deletion is worse than no log."""
    hdrs = _account(client)
    pid = _project(client, hdrs)["id"]
    client.post(f"/api/projects/{pid}/share", headers=hdrs)
    client.delete(f"/api/projects/{pid}/share", headers=hdrs)

    actions = [a["action"] for a in db.list_audit(limit=20)]
    assert "project_unshare" in actions
    assert "project_delete" not in actions[:3]
    # The project is still there.
    assert client.get(f"/api/projects/{pid}", headers=hdrs).status_code == 200
