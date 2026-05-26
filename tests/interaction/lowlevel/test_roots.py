"""Roots interactions against the low-level Server, driven through the public Client API."""

import anyio
import pytest
from inline_snapshot import snapshot
from pydantic import FileUrl

from mcp import MCPError, types
from mcp.client import ClientRequestContext
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import INTERNAL_ERROR, CallToolResult, ErrorData, ListRootsResult, Root, TextContent
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("roots:list:round-trip")
async def test_list_roots_round_trip() -> None:
    """A roots/list request from a tool handler is answered by the client's roots callback.

    The tool reports the URIs and names it received, proving the client's roots reached the server.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="show_roots", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "show_roots"
        result = await ctx.session.list_roots()
        lines = [f"{root.uri} name={root.name}" for root in result.roots]
        return CallToolResult(content=[TextContent(text="\n".join(lines))])

    server = Server("rooted", on_list_tools=list_tools, on_call_tool=call_tool)

    async def list_roots(context: ClientRequestContext) -> ListRootsResult:
        return ListRootsResult(
            roots=[
                Root(uri=FileUrl("file:///home/alice/project"), name="project"),
                Root(uri=FileUrl("file:///home/alice/scratch")),
            ]
        )

    async with Client(server, list_roots_callback=list_roots) as client:
        result = await client.call_tool("show_roots", {})

    assert result == snapshot(
        CallToolResult(
            content=[TextContent(text="file:///home/alice/project name=project\nfile:///home/alice/scratch name=None")]
        )
    )


@requirement("roots:list:empty")
async def test_list_roots_empty() -> None:
    """A client with no roots to offer answers roots/list with an empty list, not an error."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="count_roots", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "count_roots"
        result = await ctx.session.list_roots()
        return CallToolResult(content=[TextContent(text=str(len(result.roots)))])

    server = Server("rooted", on_list_tools=list_tools, on_call_tool=call_tool)

    async def list_roots(context: ClientRequestContext) -> ListRootsResult:
        return ListRootsResult(roots=[])

    async with Client(server, list_roots_callback=list_roots) as client:
        result = await client.call_tool("count_roots", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="0")]))


@requirement("roots:list:not-supported")
async def test_list_roots_without_callback_is_error() -> None:
    """A roots/list request to a client with no roots callback fails with an error the handler can observe.

    The client's default callback answers with INVALID_REQUEST rather than leaving the server
    hanging; the spec names -32601 for this case (see the divergence note on the requirement).
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="show_roots", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "show_roots"
        try:
            await ctx.session.list_roots()
        except MCPError as exc:
            return CallToolResult(content=[TextContent(text=f"{exc.error.code}: {exc.error.message}")])
        raise NotImplementedError  # list_roots cannot succeed without a client callback

    server = Server("rooted", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server) as client:
        result = await client.call_tool("show_roots", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="-32600: List roots not supported")]))


@requirement("roots:list:client-error")
async def test_list_roots_callback_error_surfaces_to_the_handler() -> None:
    """A roots callback that answers with an error fails the roots/list request with that exact error.

    The callback's code and message reach the requesting handler verbatim as an MCPError.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="show_roots", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "show_roots"
        try:
            await ctx.session.list_roots()
        except MCPError as exc:
            return CallToolResult(content=[TextContent(text=f"{exc.error.code}: {exc.error.message}")])
        raise NotImplementedError  # the callback always answers with an error

    server = Server("rooted", on_list_tools=list_tools, on_call_tool=call_tool)

    async def list_roots(context: ClientRequestContext) -> ErrorData:
        return ErrorData(code=INTERNAL_ERROR, message="roots provider crashed")

    async with Client(server, list_roots_callback=list_roots) as client:
        result = await client.call_tool("show_roots", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="-32603: roots provider crashed")]))


@requirement("roots:list-changed")
async def test_roots_list_changed_reaches_server_handler() -> None:
    """A roots/list_changed notification from the client is delivered to the server's handler.

    Unlike a request, a notification has no response to await: the handler sets an event and the
    test waits on it, which is the only synchronisation point proving delivery.
    """
    delivered = anyio.Event()
    received: list[types.NotificationParams | None] = []

    async def roots_list_changed(ctx: ServerRequestContext, params: types.NotificationParams | None) -> None:
        received.append(params)
        delivered.set()

    server = Server("rooted", on_roots_list_changed=roots_list_changed)

    async with Client(server) as client:
        await client.send_roots_list_changed()
        with anyio.fail_after(5):
            await delivered.wait()

    assert received == snapshot([None])
