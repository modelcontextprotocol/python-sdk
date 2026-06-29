"""Ping interactions against the low-level Server, driven through the public Client API."""

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import CallToolResult, EmptyResult, TextContent

from mcp.server import Server, ServerRequestContext
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("lifecycle:ping")
@requirement("ping:client-to-server")
async def test_client_ping_returns_empty_result(connect: Connect) -> None:
    server = Server("silent")

    async with connect(server) as client:
        result = await client.send_ping()  # pyright: ignore[reportDeprecated]

    assert result == snapshot(EmptyResult())


@requirement("lifecycle:ping")
@requirement("ping:server-to-client")
async def test_server_ping_returns_empty_result(connect: Connect) -> None:
    """The tool returns the pong's type name, proving the ping round trip completed inside the handler."""

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
