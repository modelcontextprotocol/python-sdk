"""Ping interactions against the low-level Server, driven through the public ClientSession API.

This file reaches the server session via the module-level `request_ctx` contextvar (pattern B
from the v1 backport's session-access spread). That contextvar is the mechanism behind
`Server.request_context`; reading it directly is a public-module-level name a v1 user can
import, and exercising it here covers the contextvar path the eventual v2 compatibility shims
must preserve.
"""

from typing import Any

import pytest
from inline_snapshot import snapshot

from mcp import types
from mcp.server import Server
from mcp.server.lowlevel.server import request_ctx
from mcp.types import CallToolResult, EmptyResult, TextContent
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("lifecycle:ping")
@requirement("ping:client-to-server")
async def test_client_ping_returns_empty_result(connect: Connect) -> None:
    """A client ping is answered with an empty result, even by a server with no handlers."""
    server: Server[None] = Server("silent")

    async with connect(server) as client:
        result = await client.send_ping()

    assert result == snapshot(EmptyResult())


@requirement("lifecycle:ping")
@requirement("ping:server-to-client")
async def test_server_ping_returns_empty_result(connect: Connect) -> None:
    """A server-initiated ping sent while a request is in flight is answered by the client.

    The tool returns the type of the ping response, proving the round trip completed inside
    the handler before the tool result was produced.
    """
    server: Server[None] = Server("pinger")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name="ping_back", description="Ping the client.", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        assert name == "ping_back"
        pong = await request_ctx.get().session.send_ping()
        return CallToolResult(content=[TextContent(type="text", text=type(pong).__name__)])

    async with connect(server) as client:
        result = await client.call_tool("ping_back", {})

    assert result == snapshot(CallToolResult(content=[TextContent(type="text", text="EmptyResult")]))
