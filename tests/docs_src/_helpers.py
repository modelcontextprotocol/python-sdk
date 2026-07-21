"""Shared helpers for the docs_src tests."""

from importlib.metadata import version
from typing import TypeVar

from mcp_types import SERVER_INFO_META_KEY, Result

from mcp.server import Server
from mcp.server.mcpserver import MCPServer

R = TypeVar("R", bound=Result)


def strip_server_info(result: R, server: Server | MCPServer) -> R:
    """Assert the 2026-era serverInfo stamp, then drop it so snapshots stay stable.

    The doc snippets set no explicit version, so the stamp's version is the
    installed mcp package version; keeping it in the inline snapshots would
    make them commit-dependent.
    """
    assert result.meta is not None
    assert result.meta[SERVER_INFO_META_KEY] == {"name": server.name, "version": version("mcp")}
    result.meta = None
    return result
