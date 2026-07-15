"""Phase 4 tests: MCP tool registry, the agentic Copilot loop (with an
injected transport — no network), vision proposal parsing, and the endpoints."""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.ai import copilot, tools


@pytest.fixture
def client():
    return TestClient(app)


# ------------------------------------------------------ tool registry
def test_tool_manifest_is_mcp_shaped():
    manifest = tools.tool_manifest()
    assert len(manifest) >= 6
    for t in manifest:
        assert set(t) == {"name", "description", "input_schema"}
        assert t["input_schema"]["type"] == "object"


def test_call_tool_runs_real_engine():
    out = tools.call_tool("repeater_design", {
        "freq_mhz": 450.0, "system_gain_db": 70.0,
        "donor_coverage_separation_m": 3.0, "reliable_range_m": 4000.0})
    assert "isolation" in out and "cascade" in out
    lf = tools.call_tool("leaky_feeder", {"freq_mhz": 450.0,
                                          "cable_length_m": 2000.0})
    assert "continuous_service_pct" in lf


def test_call_unknown_tool_raises():
    with pytest.raises(KeyError):
        tools.call_tool("does_not_exist", {})


# ------------------------------------------------------ agentic loop
def test_copilot_agentic_loop_executes_tool():
    """A scripted transport: first turn asks for a tool, second turn (after
    seeing the tool result) returns final text. The loop must execute the
    real tool and feed the result back."""
    calls = {"n": 0}

    def transport(body, cfg):
        calls["n"] += 1
        # The tool result must have been appended before the 2nd call.
        if calls["n"] == 1:
            assert any(t["name"] == "repeater_design" for t in body["tools"])
            return {"stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "tu_1", "name": "repeater_design",
                 "input": {"freq_mhz": 450.0, "system_gain_db": 70.0,
                           "donor_coverage_separation_m": 3.0}}]}
        # Second call: the previous message must be a tool_result carrying the
        # engine output.
        last = body["messages"][-1]
        assert last["role"] == "user"
        assert last["content"][0]["type"] == "tool_result"
        payload = json.loads(last["content"][0]["content"])
        assert "isolation" in payload
        return {"stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Isolation is sufficient."}]}

    cfg = {"configured": True, "model": "test", "base_url": "x", "max_tokens": 256}
    res = copilot.run_copilot("Design my repeater", transport=transport, cfg=cfg)
    assert res["reply"] == "Isolation is sufficient."
    assert res["iterations"] == 2
    assert res["tool_calls"][0]["name"] == "repeater_design"
    assert res["tool_calls"][0]["is_error"] is False


def test_copilot_reports_tool_error_to_model():
    def transport(body, cfg):
        # Always ask for a tool with bad args; loop should capture the error
        # and (on the next turn) we end.
        if not any(m["role"] == "user" and isinstance(m["content"], list)
                   and m["content"][0].get("type") == "tool_result"
                   for m in body["messages"]):
            return {"stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "t1", "name": "get_technology",
                 "input": {"key": "no_such_tech"}}]}
        return {"stop_reason": "end_turn",
                "content": [{"type": "text", "text": "handled"}]}

    cfg = {"configured": True, "model": "t", "base_url": "x", "max_tokens": 64}
    res = copilot.run_copilot("x", transport=transport, cfg=cfg)
    assert res["tool_calls"][0]["is_error"] is True
    assert res["reply"] == "handled"


def test_copilot_unconfigured_raises_without_transport():
    cfg = {"configured": False, "model": "m", "base_url": "u", "max_tokens": 64}
    with pytest.raises(RuntimeError):
        copilot.run_copilot("hi", cfg=cfg)


# ------------------------------------------------------ vision
def test_vision_parses_json_proposal():
    def transport(body, cfg):
        # Confirm an image block was sent.
        assert body["messages"][0]["content"][0]["type"] == "image"
        return {"content": [{"type": "text", "text": json.dumps({
            "materials": [{"structure": "exterior", "material": "concrete",
                           "confidence": 0.8}],
            "candidate_locations": [{"x": 0.5, "y": 0.5, "rationale": "centre"}]})}]}

    cfg = {"configured": True, "model": "t", "base_url": "x", "max_tokens": 512}
    out = copilot.propose_from_floorplan(b"\x89PNG_fake", transport=transport, cfg=cfg)
    assert out["materials"][0]["material"] == "concrete"
    assert out["candidate_locations"][0]["x"] == 0.5


def test_vision_tolerates_fenced_json():
    def transport(body, cfg):
        return {"content": [{"type": "text",
                             "text": '```json\n{"materials": [], '
                                     '"candidate_locations": []}\n```'}]}
    cfg = {"configured": True, "model": "t", "base_url": "x", "max_tokens": 64}
    out = copilot.propose_from_floorplan(b"img", transport=transport, cfg=cfg)
    assert out["materials"] == []


# ------------------------------------------------------ endpoints
def test_status_endpoint(client, monkeypatch):
    monkeypatch.delenv("AM_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.get("/api/ai/status")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["tool_count"] >= 6


def test_tools_endpoint(client):
    r = client.get("/api/ai/tools")
    assert r.status_code == 200
    assert any(t["name"] == "leaky_feeder" for t in r.json()["tools"])


def test_tool_invoke_endpoint(client):
    r = client.post("/api/ai/tools/tunnel_link", json={
        "freq_mhz": 450.0, "width_m": 4.0, "height_m": 3.0, "length_m": 1000.0})
    assert r.status_code == 200, r.text
    assert "max_range_m" in r.json()["result"]


def test_tool_invoke_unknown_404(client):
    r = client.post("/api/ai/tools/nope", json={})
    assert r.status_code == 404


def test_chat_unconfigured_503(client, monkeypatch):
    monkeypatch.delenv("AM_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/ai/chat", json={"message": "hi"})
    assert r.status_code == 503
