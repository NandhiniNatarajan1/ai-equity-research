"""MCP server exposing SEC filing retrieval tools.

Run with:
    python -m app.mcp_server --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

from app.mcp_server.server import main, mcp

__all__ = ["main", "mcp"]
