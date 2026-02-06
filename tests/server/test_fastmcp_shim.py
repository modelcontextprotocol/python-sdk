"""Tests for the FastMCP compatibility shim."""

from __future__ import annotations


def test_fastmcp_exports() -> None:
    from mcp.server.fastmcp import FastMCP, StreamableHTTPASGIApp

    assert FastMCP is not None
    assert StreamableHTTPASGIApp is not None


def test_fastmcp_wraps_mcpserver_and_tool_decorator() -> None:
    from mcp.server.fastmcp import FastMCP

    fast_mcp = FastMCP(name="test", instructions="hi", host="127.0.0.1", port=1234)
    assert fast_mcp.host == "127.0.0.1"
    assert fast_mcp.port == 1234
    assert getattr(fast_mcp, "_mcp_server", None) is not None

    @fast_mcp.tool()
    def hello() -> str:
        return "world"

    assert hello() == "world"
