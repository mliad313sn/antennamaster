"""The expensive endpoints must not be an unlimited free resource.

A coverage study is seconds of CPU over a numpy grid plus a burst of DEM tile
fetches. Every one of those endpoints was reachable unauthenticated with no
quota, no queue and no throttle, so a loop from one IP was a free denial of
service against every other tenant on the box — and the upload routes were the
same thing pointed at the disk (100 MB per DXF).
"""
import time

import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import _cost_class
from app.main import app
from app.services.saas import ratelimit
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    # Undo the suite-wide opt-out: this file is where the guard is the
    # behaviour under test.
    monkeypatch.setenv("AM_RATE_LIMIT", "1")
    ratelimit.reset()
    yield TestClient(app)
    ratelimit.reset()


BODY = {"lat": 47.0, "lon": 15.0, "technology": "pmr446", "radius_km": 1,
        "resolution_m": 500}


def test_an_anonymous_loop_is_cut_off_with_a_retry_after(client):
    limit = ratelimit.LIMITS["compute"]["anon"][0]
    last = None
    for _ in range(limit + 2):
        last = client.post("/api/rf/coverage", json=BODY)
        if last.status_code == 429:
            break
    assert last.status_code == 429, "an unbounded anonymous loop was allowed"
    # A 429 without Retry-After just makes a badly written client hammer
    # harder; the number must be usable.
    assert int(last.headers["Retry-After"]) >= 1
    assert "sign in" in last.json()["detail"]


def test_an_authenticated_caller_gets_the_larger_allowance(client):
    r = client.post("/api/auth/register", json={
        "email": f"rl{time.time_ns()}@x.io", "password": "hunter22secure",
        "role": "field", "org_name": ""})
    hdrs = {"Authorization": f"Bearer {r.json()['token']}"}

    anon_limit = ratelimit.LIMITS["compute"]["anon"][0]
    for _ in range(anon_limit + 1):
        resp = client.post("/api/rf/coverage", json=BODY, headers=hdrs)
        assert resp.status_code != 429, "signing in must buy a real allowance"


def test_a_garbage_token_cannot_mint_a_fresh_budget(client):
    """The obvious bypass: key the bucket on the bearer token and vary it.

    A token that does not resolve must fall back to the client IP, or the
    limit is decorative.
    """
    limit = ratelimit.LIMITS["compute"]["anon"][0]
    last = None
    for i in range(limit + 2):
        last = client.post("/api/rf/coverage", json=BODY,
                           headers={"Authorization": f"Bearer forged-{i}"})
        if last.status_code == 429:
            break
    assert last.status_code == 429


def test_uploads_have_their_own_much_tighter_budget(client, site_dxf):
    """Disk, not CPU: a DXF may be 100 MB. The upload budget must not be
    spendable by making cheap compute calls, nor vice versa."""
    upload_limit = ratelimit.LIMITS["upload"]["anon"][0]
    codes = []
    for _ in range(upload_limit + 1):
        with open(site_dxf, "rb") as fh:
            codes.append(client.post("/api/dxf/upload",
                                     files={"file": ("site.dxf", fh)}).status_code)
    assert 429 in codes
    # The compute budget is untouched by the uploads.
    assert client.post("/api/rf/coverage", json=BODY).status_code != 429


def test_cheap_metadata_reads_are_never_limited(client):
    for _ in range(60):
        assert client.get("/api/rf/technologies").status_code == 200
    assert _cost_class("GET", "/api/rf/technologies") is None


def test_the_limits_can_be_disabled_for_an_air_gapped_install(client,
                                                              monkeypatch):
    """One engineer on an isolated box should not be throttled by a guard
    aimed at an internet-facing loop."""
    monkeypatch.setenv("AM_RATE_LIMIT", "0")
    ratelimit.reset()
    limit = ratelimit.LIMITS["compute"]["anon"][0]
    for _ in range(limit + 3):
        assert client.post("/api/rf/coverage", json=BODY).status_code != 429


def test_the_window_slides_rather_than_resetting_on_a_boundary(monkeypatch):
    """A fixed window lets a caller spend the whole budget at the end of one
    and again at the start of the next — a 2x burst exactly when the box is
    already loaded."""
    monkeypatch.setenv("AM_RATE_LIMIT", "1")
    ratelimit.reset()
    limit, window = ratelimit.LIMITS["compute"]["anon"]
    t0 = 1_000_000.0
    for i in range(limit):
        assert ratelimit.check("compute", "1.2.3.4", False, now=t0 + i) is None
    assert ratelimit.check("compute", "1.2.3.4", False, now=t0 + limit) is not None
    # Only as the *oldest* hit ages out does one slot come back - not the
    # whole budget at once.
    assert ratelimit.check("compute", "1.2.3.4", False,
                           now=t0 + window + 0.5) is None
    assert ratelimit.check("compute", "1.2.3.4", False,
                           now=t0 + window + 0.6) is not None
