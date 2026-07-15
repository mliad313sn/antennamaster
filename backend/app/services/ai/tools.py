"""Simulation tool registry exposed to the AI Copilot and over MCP.

Each tool wraps an existing AntennaMaster engine as an MCP-format tool
(``name`` / ``description`` / ``input_schema``) with a pure-Python handler.
The same registry backs three surfaces:

* the in-process **Copilot** agentic loop (``copilot.py``),
* the **HTTP tool API** (``GET /api/ai/tools``, ``POST /api/ai/tools/{name}``)
  that an external MCP bridge calls,
* the standalone **MCP stdio server** (``backend/mcp_server.py``).

Handlers here are deliberately the *self-contained* engines (no live DEM /
network needed) so the Copilot can compute link budgets, repeater designs,
leaky-feeder runs and tunnel/TTE studies deterministically and offline.
"""
from __future__ import annotations

from typing import Any, Callable

from ..rf.technologies import (TECHNOLOGIES, get_technology, link_budget)
from ..rf.models import MODEL_INFO
from ..rf import talkback as _tb
from ..rf import underground as _ug


# --------------------------------------------------------------------------- #
#  Handlers (return JSON-serializable dicts)
# --------------------------------------------------------------------------- #
def _h_list_technologies(_: dict) -> dict:
    return {"technologies": [{"key": k, "label": v.get("label", k),
                              "generation": v.get("generation"),
                              "freq_mhz": v.get("freq_mhz")}
                             for k, v in TECHNOLOGIES.items()]}


def _h_list_models(_: dict) -> dict:
    return {"models": [{"key": k, **v} for k, v in MODEL_INFO.items()]}


def _h_get_technology(args: dict) -> dict:
    return get_technology(args["key"])


def _h_link_budget(args: dict) -> dict:
    tech = get_technology(args["technology"])
    for f in ("freq_mhz", "tx_power_dbm", "tx_gain_dbi", "rx_gain_dbi",
              "losses_db", "rx_sensitivity_dbm"):
        if args.get(f) is not None:
            tech[f] = args[f]
    return link_budget(tech, float(args["path_loss_db"]),
                       diffraction_db=float(args.get("diffraction_db", 0.0)),
                       extra_losses_db=float(args.get("extra_losses_db", 0.0)))


def _h_repeater_design(args: dict) -> dict:
    return _tb.repeater_design(
        float(args["freq_mhz"]), float(args["system_gain_db"]),
        float(args["donor_coverage_separation_m"]),
        arrangement=args.get("arrangement", "vertical"),
        stability_margin_db=float(args.get("stability_margin_db", 15.0)),
        reliable_range_m=(float(args["reliable_range_m"])
                          if args.get("reliable_range_m") is not None else None),
        overlap_fraction=float(args.get("overlap_fraction", 0.15)))


def _h_leaky_feeder(args: dict) -> dict:
    return _ug.leaky_feeder_profile(
        float(args["freq_mhz"]), float(args["cable_length_m"]),
        cable=args.get("cable", "rc78"),
        head_end_dbm=float(args.get("head_end_dbm", 20.0)),
        amp_gain_db=float(args.get("amp_gain_db", 30.0)),
        rx_sensitivity_dbm=float(args.get("rx_sensitivity_dbm", -95.0)),
        design_margin_db=float(args.get("design_margin_db", 10.0)),
        radial_distance_m=float(args.get("radial_distance_m", 2.0)))


def _h_tunnel_link(args: dict) -> dict:
    wall = args.get("wall", "rock")
    eps = _ug.TUNNEL_WALL_PRESETS.get(wall, _ug.TUNNEL_WALL_PRESETS["rock"])["eps_r"]
    return _ug.tunnel_profile(
        float(args["freq_mhz"]), float(args["width_m"]), float(args["height_m"]),
        float(args["length_m"]), eps_r=eps,
        tx_power_dbm=float(args.get("tx_power_dbm", 30.0)),
        rx_sensitivity_dbm=float(args.get("rx_sensitivity_dbm", -100.0)))


def _h_tte_link(args: dict) -> dict:
    earth = args.get("earth", "average_soil")
    sigma = _ug.EARTH_PRESETS.get(earth, _ug.EARTH_PRESETS["average_soil"])["sigma"]
    return _ug.tte_link(
        float(args["freq_hz"]), float(args["depth_m"]), sigma,
        tx_power_dbm=float(args.get("tx_power_dbm", 30.0)),
        system_gain_db=float(args.get("system_gain_db", 20.0)),
        rx_sensitivity_dbm=float(args.get("rx_sensitivity_dbm", -130.0)))


# --------------------------------------------------------------------------- #
#  Registry (MCP tool format + handler)
# --------------------------------------------------------------------------- #
def _tool(name: str, description: str, properties: dict,
          required: list[str], handler: Callable[[dict], dict]) -> dict:
    return {"name": name, "description": description, "handler": handler,
            "input_schema": {"type": "object", "properties": properties,
                             "required": required}}


_NUM = {"type": "number"}
_STR = {"type": "string"}

TOOLS: dict[str, dict] = {t["name"]: t for t in [
    _tool("list_technologies",
          "List all radio technology presets (2G-5G, PMR, broadcast, Wi-Fi, "
          "IoT, PtP) with key, label, generation and frequency.",
          {}, [], _h_list_technologies),
    _tool("list_models",
          "List propagation models (FSPL, Hata family, 3GPP TR 38.901) with "
          "their frequency validity ranges.",
          {}, [], _h_list_models),
    _tool("get_technology",
          "Get the full link-budget preset for one technology key.",
          {"key": _STR}, ["key"], _h_get_technology),
    _tool("link_budget",
          "Compute RX power and fade margin for a technology given a path "
          "loss (dB) and optional diffraction / extra losses.",
          {"technology": _STR, "path_loss_db": _NUM, "diffraction_db": _NUM,
           "extra_losses_db": _NUM, "freq_mhz": _NUM, "tx_power_dbm": _NUM,
           "rx_sensitivity_dbm": _NUM},
          ["technology", "path_loss_db"], _h_link_budget),
    _tool("repeater_design",
          "Design an LMR repeater: donor/coverage antenna isolation, "
          "feedback-stable max gain, and cascade spacing for continuous "
          "talk-back along a route.",
          {"freq_mhz": _NUM, "system_gain_db": _NUM,
           "donor_coverage_separation_m": _NUM, "arrangement": _STR,
           "stability_margin_db": _NUM, "reliable_range_m": _NUM,
           "overlap_fraction": _NUM},
          ["freq_mhz", "system_gain_db", "donor_coverage_separation_m"],
          _h_repeater_design),
    _tool("leaky_feeder",
          "Design a radiating-cable (leaky feeder) run for a tunnel/metro/"
          "mine: RX vs distance, auto amplifier spacing, and the moving-train "
          "continuous-service KPI.",
          {"freq_mhz": _NUM, "cable_length_m": _NUM, "cable": _STR,
           "head_end_dbm": _NUM, "amp_gain_db": _NUM, "rx_sensitivity_dbm": _NUM,
           "design_margin_db": _NUM, "radial_distance_m": _NUM},
          ["freq_mhz", "cable_length_m"], _h_leaky_feeder),
    _tool("tunnel_link",
          "Waveguide-regime signal profile along a straight tunnel/mine "
          "gallery (Emslie model).",
          {"freq_mhz": _NUM, "width_m": _NUM, "height_m": _NUM,
           "length_m": _NUM, "wall": _STR, "tx_power_dbm": _NUM,
           "rx_sensitivity_dbm": _NUM},
          ["freq_mhz", "width_m", "height_m", "length_m"], _h_tunnel_link),
    _tool("tte_link",
          "Through-the-earth VLF link budget through conductive ground "
          "(mine/cave rescue paging).",
          {"freq_hz": _NUM, "depth_m": _NUM, "earth": _STR,
           "tx_power_dbm": _NUM, "system_gain_db": _NUM,
           "rx_sensitivity_dbm": _NUM},
          ["freq_hz", "depth_m"], _h_tte_link),
]}


def tool_manifest() -> list[dict]:
    """MCP-format tool list (no handlers) for tools/list and the HTTP API."""
    return [{"name": t["name"], "description": t["description"],
             "input_schema": t["input_schema"]} for t in TOOLS.values()]


def call_tool(name: str, args: dict[str, Any] | None = None) -> dict:
    """Invoke a registered tool by name.  Raises KeyError if unknown."""
    if name not in TOOLS:
        raise KeyError(f"Unknown tool: {name!r}")
    return TOOLS[name]["handler"](args or {})
