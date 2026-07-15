"""Tests: design copilot (advisor, narration, tool catalog, analyze endpoints)."""
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.copilot.advisor import (advise_coverage, advise_link,
                                          narrate, narrate_llm)
from app.services.copilot.tools import tool_catalog
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


# ------------------------------------------------------------- unit: advisor
def test_advise_link_flags_failed_budget_with_quantified_fix():
    analysis = {"margin_db": -12.0, "los_clear": True,
                "fresnel_clearance_ratio": 0.9, "diffraction_loss_db": 2.0,
                "distance_m": 8000.0, "freq_mhz": 5800.0}
    findings = advise_link(analysis)
    top = findings[0]
    assert top["severity"] == "critical"
    assert "12" in top["action"]                 # quantifies the 12 dB deficit
    assert "does not close" in top["issue"].lower()


def test_advise_link_obstruction_quotes_mast_height():
    analysis = {"margin_db": 3.0, "los_clear": False,
                "fresnel_clearance_ratio": 0.1, "diffraction_loss_db": 25.0,
                "distance_m": 10_000.0, "freq_mhz": 900.0}
    heights = {"criteria": {"f1_60": {"min_tx_height_m": 42.0},
                            "los": {"min_tx_height_m": 30.0}}}
    findings = advise_link(analysis, heights)
    obstruction = [f for f in findings if "obstruct" in f["issue"].lower()]
    assert obstruction and "42" in obstruction[0]["action"]


def test_advise_link_healthy_when_strong():
    analysis = {"margin_db": 25.0, "los_clear": True,
                "fresnel_clearance_ratio": 1.2, "diffraction_loss_db": 0.0,
                "distance_m": 3000.0, "freq_mhz": 900.0}
    findings = advise_link(analysis)
    assert len(findings) == 1 and findings[0]["severity"] == "good"


def test_advise_coverage_holes_and_interference():
    holes = advise_coverage({"served_area_fraction": 0.6})
    assert holes[0]["severity"] == "critical"
    interf = advise_coverage({"served_area_fraction": 0.95},
                             sinr={"mean_sinr_db": 3.0})
    assert any("interference" in f["issue"].lower() for f in interf)


def test_narrate_offline_and_llm_fallback(monkeypatch):
    findings = advise_link({"margin_db": -5.0, "los_clear": True,
                            "fresnel_clearance_ratio": 1.0,
                            "diffraction_loss_db": 0.0,
                            "distance_m": 5000.0, "freq_mhz": 900.0})
    text = narrate(findings, "radio link")
    assert "radio link" in text and "-" in text
    # With no API key, the LLM narrator must fall back to the offline text.
    monkeypatch.delenv("AM_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert narrate_llm(findings, "radio link") == narrate(findings, "radio link")


# --------------------------------------------------------------- unit: tools
def test_tool_catalog_shape():
    tools = tool_catalog()
    assert len(tools) >= 8
    for t in tools:
        assert {"name", "method", "path", "purpose", "parameters"} <= t.keys()
        assert t["path"].startswith("/api/")


# ------------------------------------------------------------- API layer
def test_copilot_tools_api(client):
    resp = client.get("/api/copilot/tools")
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()["tools"]]
    assert "two_way_talkback" in names and "auto_place_aps" in names


def test_copilot_analyze_link_api(client):
    # A long high-band hop over the ramp world: expect actionable findings.
    body = {"tx_lat": 47.0, "tx_lon": 15.0, "rx_lat": 47.0, "rx_lon": 15.3,
            "technology": "wifi5800"}
    resp = client.post("/api/copilot/analyze/link", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "analysis" in data and "findings" in data and "summary" in data
    assert data["findings"] and "severity" in data["findings"][0]


def test_copilot_analyze_coverage_api(client):
    body = {"stats": {"served_area_fraction": 0.55}, "technology": "nr3500"}
    resp = client.post("/api/copilot/analyze/coverage", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert any(f["severity"] == "critical" for f in data["findings"])
