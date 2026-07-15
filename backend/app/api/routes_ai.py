"""AI Copilot & MCP tool endpoints.

* ``GET  /api/ai/status``            — is the Copilot configured, which model.
* ``GET  /api/ai/tools``             — MCP-format tool manifest.
* ``POST /api/ai/tools/{name}``      — invoke a simulation tool by name.
* ``POST /api/ai/chat``              — the agentic Design Copilot (runs tools).
* ``POST /api/ai/vision/floorplan``  — propose wall materials + AP locations
                                        from a floor-plan image (vision).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..services.ai import copilot, tools
from .routes_auth import current_user

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status")
def ai_status() -> dict:
    """Copilot configuration (no secrets): whether an API key / endpoint is
    set and which model would be used."""
    cfg = copilot.config()
    return {"configured": cfg["configured"], "model": cfg["model"],
            "base_url": cfg["base_url"], "tool_count": len(tools.TOOLS)}


@router.get("/tools")
def ai_tools() -> dict:
    """MCP-format manifest of the simulation tools the Copilot (or an external
    MCP client) can call."""
    return {"tools": tools.tool_manifest()}


@router.post("/tools/{name}")
def ai_call_tool(name: str, args: dict | None = None) -> dict:
    """Invoke a simulation tool directly — the same entry point the Copilot
    and the MCP bridge use.  Deterministic and offline."""
    try:
        return {"tool": name, "result": tools.call_tool(name, args or {})}
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - bad args -> 422
        raise HTTPException(422, f"Tool {name!r} failed: {exc}") from exc


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    history: list[dict] | None = None
    max_iterations: int = Field(6, ge=1, le=12)


@router.post("/chat")
def ai_chat(req: ChatRequest,
            user: dict | None = Depends(current_user)) -> dict:
    """Design Copilot: interprets the request, calls simulation tools as
    needed, and returns a plain-language answer plus the tool-call trace."""
    if not copilot.config()["configured"]:
        raise HTTPException(503, "Copilot is not configured on this server "
                                 "(set AM_ANTHROPIC_API_KEY or AM_LLM_BASE_URL).")
    try:
        return copilot.run_copilot(req.message, history=req.history,
                                   max_iterations=req.max_iterations)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Copilot error: {exc}") from exc


@router.post("/vision/floorplan")
async def ai_vision_floorplan(file: UploadFile = File(...),
                              user: dict | None = Depends(current_user)) -> dict:
    """Vision: from an uploaded floor-plan image, propose a wall material per
    visible structure and candidate AP/mast locations (fractional coords)."""
    if not copilot.config()["configured"]:
        raise HTTPException(503, "Copilot is not configured on this server "
                                 "(set AM_ANTHROPIC_API_KEY or AM_LLM_BASE_URL).")
    data = await file.read()
    if not data:
        raise HTTPException(422, "Empty image upload.")
    media_type = file.content_type or "image/png"
    try:
        return copilot.propose_from_floorplan(data, media_type=media_type)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Vision analysis failed: {exc}") from exc
