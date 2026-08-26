"""Robustness fixes found by probing a running server with hostile input.

Both cases below were reproduced against a live backend before being fixed:
a NaN in a validated numeric field returned 500 instead of 422, and an
unreachable elevation source could pin a worker for minutes.
"""
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import _json_safe, app
from app.services.dem.tiles import TerrariumTileStore


@pytest.fixture
def client():
    return TestClient(app)


# --------------------------------------------------------------- NaN handling
def test_nan_in_body_is_rejected_as_bad_input_not_a_server_error(client):
    """json.loads accepts NaN on the way in, but it cannot be serialized back
    out - so FastAPI's default handler, which echoes the rejected value,
    turned a clean 422 into a 500. Verified against a live server."""
    r = client.post("/api/rf/coverage",
                    content=b'{"lat": NaN, "lon": 15, "technology": "gsm900", '
                            b'"radius_km": 5}',
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 422, "NaN must be bad input, never a server error"
    assert r.json()["detail"], "the client is told what was wrong"


def test_infinity_in_body_is_also_a_422(client):
    r = client.post("/api/rf/coverage",
                    content=b'{"lat": Infinity, "lon": 15, '
                            b'"technology": "gsm900", "radius_km": 5}',
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_json_safe_preserves_everything_finite():
    payload = {"a": 1.5, "b": [2, "x", {"c": -3.25}], "d": None, "e": True}
    assert _json_safe(payload) == payload


def test_json_safe_stringifies_only_the_non_finite_parts():
    out = _json_safe({"ok": 1.0, "bad": float("nan"),
                      "worse": [float("inf"), 2.0]})
    assert out["ok"] == 1.0
    assert out["bad"] == "nan"
    assert out["worse"] == ["inf", 2.0]


# ------------------------------------------------- DEM source circuit breaker
class _DeadSource(TerrariumTileStore):
    """A tile source whose every request fails, counting the attempts."""

    def __init__(self, tmp_path):
        super().__init__(cache_dir=tmp_path)
        self.attempts = 0

        class _Client:
            def get(_self, url):
                self.attempts += 1
                raise httpx.ConnectTimeout("source unreachable")

        self._client = _Client()


def test_unreachable_source_fails_fast_instead_of_retrying_every_tile(tmp_path):
    """One study can need hundreds of uncached tiles; at 30 s each, serially
    retrying a dead host would hold a worker slot for many minutes."""
    store = _DeadSource(tmp_path)

    # The first few attempts really try, then the breaker opens.
    for i in range(3):
        with pytest.raises(httpx.ConnectTimeout):
            store.get_tile(12, 100 + i, 200)
    assert store.attempts == 3

    # Every later tile in the same study is refused without touching the net.
    for i in range(50):
        with pytest.raises(TerrariumTileStore.SourceUnavailable):
            store.get_tile(12, 200 + i, 300)
    assert store.attempts == 3, "breaker must stop further network attempts"


def test_breaker_probes_again_after_the_cooldown(tmp_path, monkeypatch):
    store = _DeadSource(tmp_path)
    for i in range(3):
        with pytest.raises(httpx.ConnectTimeout):
            store.get_tile(12, 100 + i, 200)
    with pytest.raises(TerrariumTileStore.SourceUnavailable):
        store.get_tile(12, 400, 400)

    # Jump past the cooldown: the source must get another chance, so a
    # transient outage does not disable elevation for the process lifetime.
    later = time.monotonic() + TerrariumTileStore._COOLDOWN_S + 1
    monkeypatch.setattr(time, "monotonic", lambda: later)
    with pytest.raises(httpx.ConnectTimeout):
        store.get_tile(12, 401, 400)
    assert store.attempts == 4


def test_a_success_resets_the_failure_count(tmp_path):
    store = TerrariumTileStore(cache_dir=tmp_path)
    store._note_fetch_failure()
    store._note_fetch_failure()
    store._note_fetch_success()
    store._note_fetch_failure()
    store._raise_if_source_down()          # 1 failure - must not raise
