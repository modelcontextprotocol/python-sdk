"""Ping interactions against the low-level Server, driven through the public Client API."""

import pytest
from inline_snapshot import snapshot

from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.types import CallToolResult, EmptyResult, TextContent
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("lifecycle:ping")
@requirement("ping:client-to-server")
async def test_client_ping_returns_empty_result(connect: Connect) -> None:
    """A client ping is answered with an empty result, even by a server with no handlers."""
    server = Server("silent")

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

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="ping_back", description="Ping the client.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ping_back"
        pong = await ctx.session.send_ping()
        return CallToolResult(content=[TextContent(text=type(pong).__name__)])

    server = Server("pinger", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        result = await client.call_tool("ping_back", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="EmptyResult")]))
