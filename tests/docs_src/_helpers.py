"""Shared helpers for the docs_src tests."""

from typing import TypeVar

from mcp_types import SERVER_INFO_META_KEY, Result

from mcp.server import Server
from mcp.server.mcpserver import MCPServer

R = TypeVar("R", bound=Result)


def strip_server_info(result: R, server: Server | MCPServer) -> R:
    """Assert the 2026-era serverInfo stamp, then drop it so snapshots stay focused.

    The doc snippets set no explicit version, so the stamp's version is empty;
    the fenced outputs in the docs pages leave the stamp out, and the tests
    mirror the fences.
    """
    assert result.meta is not None
    assert result.meta[SERVER_INFO_META_KEY] == {"name": server.name, "version": ""}
    result.meta = None
    return result
