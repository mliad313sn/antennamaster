"""AntennaMaster MCP (Model Context Protocol) stdio server.

Exposes the simulation tool registry (``app.services.ai.tools``) over MCP so
any MCP-capable client — Claude Desktop, an IDE, another agent — can run
AntennaMaster studies as native tools.

Run:
    python -m mcp_server            # requires the `mcp` package

The same registry is always available over HTTP (``GET /api/ai/tools`` +
``POST /api/ai/tools/{name}``), so this stdio server is optional: it is only
needed for stdio-based MCP hosts.  The import of the SDK is guarded so a
missing ``mcp`` dependency degrades to a clear message instead of a crash.
"""
from __future__ import annotations

import sys

from app.services.ai.tools import TOOLS, call_tool, tool_manifest


def main() -> int:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        sys.stderr.write(
            "The `mcp` package is not installed. Install it with "
            "`pip install mcp` to run the stdio MCP server, or use the HTTP "
            "tool API at GET /api/ai/tools and POST /api/ai/tools/{name}.\n")
        return 1

    server = FastMCP("antennamaster")

    # Register each simulation tool with the MCP server.  Each MCP tool takes a
    # single JSON object (``args``) and returns the engine's dict result.
    def _make(tool_name: str):
        def _run(args: dict | None = None) -> dict:
            return call_tool(tool_name, args or {})
        _run.__name__ = tool_name
        return _run

    for name, spec in TOOLS.items():
        server.tool(name=name, description=spec["description"])(_make(name))

    sys.stderr.write(f"AntennaMaster MCP server: {len(tool_manifest())} tools "
                     "over stdio.\n")
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
