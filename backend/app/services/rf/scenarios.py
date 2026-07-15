"""Plain-language deployment scenarios for the non-technical "Simple Mode".

Operational site managers and logistics partners don't think in dBi, MHz or
Okumura-Hata — they think "connect two buildings" or "Wi-Fi for the vehicle
fleet".  Each scenario here maps such an outcome to the correct underlying
technology preset plus sensible study defaults (radius, antenna, fade
margin), so the frontend can hide the RF knobs entirely and still drive the
same physics engine.

``label``/``blurb`` are i18n keys (resolved in the frontend), not display
text, so this mapping stays language-neutral.
"""
from __future__ import annotations

from .technologies import TECHNOLOGIES

# id -> scenario definition.  ``technology`` must exist in TECHNOLOGIES.
SCENARIOS: dict[str, dict] = {
    "buildings_ptp": {
        "label": "scenario.buildings_ptp.label",
        "blurb": "scenario.buildings_ptp.blurb",
        "icon": "🏢",
        "technology": "wifi5800",
        "study": "profile",          # point-to-point link
        "tx_height_m": 15.0, "rx_height_m": 15.0,
        "sector": False,
    },
    "backhaul_longhop": {
        "label": "scenario.backhaul_longhop.label",
        "blurb": "scenario.backhaul_longhop.blurb",
        "icon": "📡",
        "technology": "ptp18000",
        "study": "profile",
        "tx_height_m": 30.0, "rx_height_m": 30.0,
        "sector": False,
    },
    "fleet_wifi": {
        "label": "scenario.fleet_wifi.label",
        "blurb": "scenario.fleet_wifi.blurb",
        "icon": "🚚",
        "technology": "wifi2400",
        "study": "coverage",
        "radius_km": 3.0, "tx_height_m": 12.0,
        "sector": False, "shadow_margin_db": 6.0,
    },
    "site_radios": {
        "label": "scenario.site_radios.label",
        "blurb": "scenario.site_radios.blurb",
        "icon": "📻",
        "technology": "pmr446",
        "study": "coverage",
        "radius_km": 5.0, "tx_height_m": 30.0,
        "sector": False, "shadow_margin_db": 6.0,
    },
    "private_lte_site": {
        "label": "scenario.private_lte_site.label",
        "blurb": "scenario.private_lte_site.blurb",
        "icon": "🏭",
        "technology": "private_lte_b48",
        "study": "coverage",
        "radius_km": 4.0, "tx_height_m": 15.0,
        "sector": True, "shadow_margin_db": 8.0,
    },
    "iot_sensors": {
        "label": "scenario.iot_sensors.label",
        "blurb": "scenario.iot_sensors.blurb",
        "icon": "🌡️",
        "technology": "lora868",
        "study": "coverage",
        "radius_km": 12.0, "tx_height_m": 25.0,
        "sector": False, "shadow_margin_db": 6.0,
    },
    "mobile_coverage": {
        "label": "scenario.mobile_coverage.label",
        "blurb": "scenario.mobile_coverage.blurb",
        "icon": "📱",
        "technology": "lte1800",
        "study": "coverage",
        "radius_km": 8.0, "tx_height_m": 30.0,
        "sector": True, "shadow_margin_db": 8.0,
    },
}


def list_scenarios() -> list[dict]:
    """Scenarios enriched with the resolved preset's human-facing summary
    (frequency band label, power) so Simple Mode can show a reassuring
    'this uses…' line without exposing the raw RF fields."""
    out = []
    for sid, s in SCENARIOS.items():
        tech = TECHNOLOGIES.get(s["technology"], {})
        out.append({
            "id": sid,
            "label": s["label"],
            "blurb": s["blurb"],
            "icon": s["icon"],
            "study": s["study"],
            "technology": s["technology"],
            "technology_label": tech.get("label", s["technology"]),
            "defaults": {k: s[k] for k in (
                "radius_km", "tx_height_m", "rx_height_m", "sector",
                "shadow_margin_db") if k in s},
        })
    return out


def resolve_scenario(scenario_id: str) -> dict:
    """The full study parameters for one scenario, or raise KeyError."""
    s = SCENARIOS[scenario_id]
    tech = TECHNOLOGIES.get(s["technology"], {})
    return {
        "id": scenario_id,
        "technology": s["technology"],
        "technology_label": tech.get("label", s["technology"]),
        "study": s["study"],
        "radius_km": s.get("radius_km"),
        "tx_height_m": s.get("tx_height_m", tech.get("h_bs_m", 30.0)),
        "rx_height_m": s.get("rx_height_m", tech.get("h_ut_m", 1.5)),
        "sector": s.get("sector", False),
        "shadow_margin_db": s.get("shadow_margin_db", 0.0),
    }
