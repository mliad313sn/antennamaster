"""AntennaMaster Design Copilot.

An agentic loop over the Anthropic Messages API (or any Anthropic-compatible
endpoint — set ``AM_LLM_BASE_URL`` to a local gateway for air-gapped sites).
The Copilot is given the simulation tool registry (``tools.py``) so it can
*actually run* studies — "design a leaky feeder for a 3 km tunnel", "what
repeater isolation do I need at 450 MHz with 85 dB gain" — execute the tool,
read the numbers back, and explain the result.

Design choices for a self-hostable product:

* **No SDK dependency** — the Anthropic wire protocol is spoken directly with
  ``httpx`` (already a dependency), so installs stay light and a local
  OpenAI-to-Anthropic proxy can be dropped in via base-URL override.
* **Graceful when unconfigured** — with no API key the chat/vision endpoints
  report ``configured: false`` and 503 instead of crashing; every other
  feature of the platform is unaffected.
* **Injectable transport** — ``run_copilot(..., transport=...)`` accepts a
  callable so the agentic loop is unit-tested without any network.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any, Callable

import httpx

from .tools import call_tool, tool_manifest

SYSTEM_PROMPT = (
    "You are the AntennaMaster Design Copilot, an expert RF systems engineer. "
    "Help the user plan radio coverage, LMR talk-back, tunnel/mine leaky "
    "feeders, repeaters and indoor AP layouts. When a question needs numbers, "
    "CALL THE PROVIDED TOOLS to compute them rather than guessing, then explain "
    "the result in plain language with the key figures and a concrete "
    "recommendation (e.g. raise the mast, add a repeater, change cable). Be "
    "concise and quantitative. State assumptions explicitly."
)


def config() -> dict:
    """Copilot configuration from the environment (never returns the key)."""
    key = os.environ.get("AM_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    return {
        "configured": bool(key),
        "model": os.environ.get("AM_COPILOT_MODEL", "claude-sonnet-5"),
        "base_url": os.environ.get("AM_LLM_BASE_URL", "https://api.anthropic.com"),
        "max_tokens": int(os.environ.get("AM_COPILOT_MAX_TOKENS", "1024")),
    }


def _api_key() -> str | None:
    return os.environ.get("AM_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")


def _default_transport(body: dict, cfg: dict) -> dict:
    """POST one Messages-API request and return the parsed JSON."""
    url = cfg["base_url"].rstrip("/") + "/v1/messages"
    headers = {"x-api-key": _api_key() or "",
               "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        return resp.json()


def _anthropic_tools() -> list[dict]:
    return [{"name": t["name"], "description": t["description"],
             "input_schema": t["input_schema"]} for t in tool_manifest()]


def run_copilot(user_message: str, history: list[dict] | None = None,
                max_iterations: int = 6,
                transport: Callable[[dict, dict], dict] | None = None,
                cfg: dict | None = None) -> dict:
    """Run the agentic loop for one user turn.

    Returns ``{reply, tool_calls, iterations, stop_reason}``.  ``transport`` is
    injectable (defaults to the live Anthropic call) so the loop is testable.
    """
    cfg = cfg or config()
    if not cfg["configured"] and transport is None:
        raise RuntimeError("Copilot is not configured (set AM_ANTHROPIC_API_KEY).")
    send = transport or _default_transport

    messages: list[dict] = list(history or [])
    messages.append({"role": "user", "content": user_message})
    tools = _anthropic_tools()
    tool_calls: list[dict] = []

    stop_reason = None
    for i in range(max_iterations):
        body = {"model": cfg["model"], "max_tokens": cfg["max_tokens"],
                "system": SYSTEM_PROMPT, "messages": messages, "tools": tools}
        data = send(body, cfg)
        stop_reason = data.get("stop_reason")
        content = data.get("content", [])
        messages.append({"role": "assistant", "content": content})

        tool_uses = [b for b in content if b.get("type") == "tool_use"]
        if not tool_uses:
            texts = [b.get("text", "") for b in content if b.get("type") == "text"]
            return {"reply": "\n".join(t for t in texts if t).strip(),
                    "tool_calls": tool_calls, "iterations": i + 1,
                    "stop_reason": stop_reason}

        results = []
        for tu in tool_uses:
            name, args = tu.get("name"), tu.get("input", {})
            try:
                out = call_tool(name, args)
                is_error = False
            except Exception as exc:  # noqa: BLE001 - report tool errors to the model
                out, is_error = {"error": str(exc)}, True
            tool_calls.append({"name": name, "input": args, "output": out,
                               "is_error": is_error})
            results.append({"type": "tool_result", "tool_use_id": tu.get("id"),
                            "content": json.dumps(out), "is_error": is_error})
        messages.append({"role": "user", "content": results})

    return {"reply": "", "tool_calls": tool_calls, "iterations": max_iterations,
            "stop_reason": stop_reason or "max_iterations"}


# --------------------------------------------------------------------------- #
#  Vision: floor-plan interpretation
# --------------------------------------------------------------------------- #
VISION_PROMPT = (
    "You are analysing an uploaded building floor plan for RF planning. "
    "Identify the wall/partition structures and, for each visually distinct "
    "structure type, propose the most likely material from this library: "
    "drywall, wood, glass, glass_coated, brick, concrete, concrete_thick, "
    "metal. Also propose 1-6 candidate access-point / mast locations as "
    "fractional coordinates (x,y in 0..1 from the top-left) that would give "
    "good coverage. Respond ONLY with JSON of the form "
    '{"materials": [{"structure": str, "material": str, "confidence": 0-1}], '
    '"candidate_locations": [{"x": float, "y": float, "rationale": str}]}.'
)


def propose_from_floorplan(image_bytes: bytes, media_type: str = "image/png",
                           transport: Callable[[dict, dict], dict] | None = None,
                           cfg: dict | None = None) -> dict:
    """Vision call: propose wall materials and candidate AP/mast locations from
    a floor-plan image.  Returns the parsed JSON proposal (best-effort)."""
    cfg = cfg or config()
    if not cfg["configured"] and transport is None:
        raise RuntimeError("Copilot is not configured (set AM_ANTHROPIC_API_KEY).")
    send = transport or _default_transport
    b64 = base64.b64encode(image_bytes).decode("ascii")
    body = {
        "model": cfg["model"], "max_tokens": cfg["max_tokens"],
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
                                         "media_type": media_type, "data": b64}},
            {"type": "text", "text": VISION_PROMPT}]}],
    }
    data = send(body, cfg)
    texts = [b.get("text", "") for b in data.get("content", [])
             if b.get("type") == "text"]
    raw = "\n".join(texts).strip()
    try:
        # Tolerate a fenced ```json block.
        cleaned = raw
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        proposal = json.loads(cleaned)
    except (ValueError, IndexError):
        proposal = {"materials": [], "candidate_locations": [], "raw": raw}
    return proposal
