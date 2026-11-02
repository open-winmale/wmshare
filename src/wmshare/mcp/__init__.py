"""Local MCP server for wmshare.

The implementation is intentionally isolated here so that ``pip install
wmshare`` keeps working without the optional MCP dependency.
"""

from __future__ import annotations

from wmshare.mcp.constants import TOOL_NAMES

__all__ = ["TOOL_NAMES"]


def __getattr__(name: str):
    # Keep ``import wmshare.mcp`` cheap and usable before the optional
    # dependency is installed.  Protocol helpers import FastMCP only when used.
    if name == "build_server":
        from wmshare.mcp.server import build_server

        return build_server
    if name == "main":
        from wmshare.mcp.cli import main

        return main
    raise AttributeError(name)
