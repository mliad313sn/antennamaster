"""Tool catalog -- the durable foundation of the AI layer.

Exposes the simulator's study endpoints as machine-readable tool schemas so an
AI copilot (or any external agent, via MCP or a plain function-calling loop)
can *call* the simulator, not just talk about it.  The catalog is intentionally
a thin description of already-authenticated HTTP endpoints: the agent decides
*which* study to run and with *what* parameters; the existing routes do the
physics and enforce their own auth/limits.
"""
from __future__ import annotations

# Each tool: a name, the HTTP method+path to call, a one-line purpose and the
# JSON-schema-ish parameter summary the agent fills in.
TOOL_CATALOG = [
    {"name": "terrain_profile",
     "method": "GET", "path": "/api/terrain/profile",
     "purpose": "Terrain profile + line-of-sight/Fresnel/link analysis for a "
                "TX->RX path (add technology= for a full link budget).",
     "parameters": {"lat1": "float", "lon1": "float", "lat2": "float",
                    "lon2": "float", "technology": "str?", "surface": "bool?"}},
    {"name": "itm_path_loss",
     "method": "GET", "path": "/api/terrain/itm",
     "purpose": "Longley-Rice irregular-terrain path loss with a reliability "
                "quantile (time/situation).",
     "parameters": {"lat1": "float", "lon1": "float", "lat2": "float",
                    "lon2": "float", "freq_mhz": "float", "reliability": "0..1",
                    "confidence": "0..1"}},
    {"name": "optimize_heights",
     "method": "GET", "path": "/api/terrain/optimize-heights",
     "purpose": "Minimum TX/RX mast heights for LOS and 60% Fresnel clearance.",
     "parameters": {"lat1": "float", "lon1": "float", "lat2": "float",
                    "lon2": "float", "freq_mhz": "float?"}},
    {"name": "area_coverage",
     "method": "POST", "path": "/api/rf/coverage",
     "purpose": "Area coverage raster + served-area statistics from one TX.",
     "parameters": {"lat": "float", "lon": "float", "technology": "str",
                    "radius_km": "float", "antenna_azimuth_deg": "float?"}},
    {"name": "multi_site_coverage",
     "method": "POST", "path": "/api/rf/coverage/multi",
     "purpose": "Best-server composite + co-channel SINR over up to 8 sites.",
     "parameters": {"sites": "list[{lat,lon}]", "technology": "str",
                    "radius_km": "float"}},
    {"name": "site_search",
     "method": "POST", "path": "/api/rf/site-search",
     "purpose": "Rank candidate TX positions in a bounding box by served area.",
     "parameters": {"south": "float", "west": "float", "north": "float",
                    "east": "float", "technology": "str"}},
    {"name": "batch_receivers",
     "method": "POST", "path": "/api/rf/batch",
     "purpose": "Qualify up to 200 receiver locations against one TX.",
     "parameters": {"lat": "float", "lon": "float", "technology": "str",
                    "receivers": "list[{lat,lon}]"}},
    {"name": "two_way_talkback",
     "method": "POST", "path": "/api/rf/twoway/link",
     "purpose": "Bidirectional LMR talk-back verdict (talk-out/talk-in, DAQ).",
     "parameters": {"base": "obj", "portable": "obj", "tx_lat": "float",
                    "tx_lon": "float", "rx_lat": "float", "rx_lon": "float"}},
    {"name": "emf_compliance",
     "method": "POST", "path": "/api/rf/compliance",
     "purpose": "ICNIRP/FCC RF-exposure exclusion-zone distances.",
     "parameters": {"freq_mhz": "float", "tx_power_dbm": "float",
                    "antenna_gain_dbi": "float", "standard": "icnirp|fcc"}},
    {"name": "auto_place_aps",
     "method": "POST", "path": "/api/indoor/auto-place",
     "purpose": "Solve AP count/positions/channels for an indoor coverage "
                "target over a floor plan.",
     "parameters": {"dxf_id": "str", "layer_materials": "obj",
                    "coverage_target": "0..1", "band": "2.4GHz|5GHz|6GHz"}},
    {"name": "leaky_feeder",
     "method": "POST", "path": "/api/indoor/leaky-feeder",
     "purpose": "Radiating-cable tunnel design: field profile + amp spacing.",
     "parameters": {"freq_mhz": "float", "length_m": "float",
                    "cable_atten_db_per_100m": "float", "amp_gain_db": "float?"}},
    {"name": "calibrate_model",
     "method": "POST", "path": "/api/rf/calibrate",
     "purpose": "Fit a model correction from measured RSSI (drive test).",
     "parameters": {"tx_lat": "float", "tx_lon": "float", "technology": "str",
                    "points": "list[{lat,lon,rssi_dbm}]"}},
]


def tool_catalog() -> list[dict]:
    return TOOL_CATALOG
