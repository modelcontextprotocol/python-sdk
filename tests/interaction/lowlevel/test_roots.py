"""Roots interactions against the low-level Server, driven through the public ClientSession API."""

from typing import Any

import anyio
import pytest
from inline_snapshot import snapshot
from pydantic import FileUrl

from mcp import McpError, types
from mcp.client.session import ClientSession
from mcp.server.lowlevel import Server
from mcp.shared.context import RequestContext
from mcp.types import INTERNAL_ERROR, CallToolResult, ErrorData, ListRootsResult, Root, TextContent
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("roots:list:basic")
async def test_list_roots_round_trip(connect: Connect) -> None:
    """A roots/list request from a tool handler is answered by the client's roots callback.

    The tool reports the URIs and names it received, proving the client's roots reached the server.
    """
    server = Server("rooted")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name="show_roots", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        assert name == "show_roots"
        result = await server.request_context.session.list_roots()
        lines = [f"{root.uri} name={root.name}" for root in result.roots]
        return [TextContent(type="text", text="\n".join(lines))]

    async def list_roots(context: RequestContext[ClientSession, Any]) -> ListRootsResult | ErrorData:
        return ListRootsResult(
            roots=[
                Root(uri=FileUrl("file:///home/alice/project"), name="project"),
                Root(uri=FileUrl("file:///home/alice/scratch")),
            ]
        )

    async with connect(server, list_roots_callback=list_roots) as client:
        result = await client.call_tool("show_roots", {})

    assert result == snapshot(
        CallToolResult(
            content=[
                TextContent(
                    type="text", text="file:///home/alice/project name=project\nfile:///home/alice/scratch name=None"
                )
            ]
        )
    )


@requirement("roots:list:empty")
async def test_list_roots_empty(connect: Connect) -> None:
    """A client with no roots to offer answers roots/list with an empty list, not an error."""
    server = Server("rooted")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name="count_roots", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        assert name == "count_roots"
        result = await server.request_context.session.list_roots()
        return [TextContent(type="text", text=str(len(result.roots)))]

    async def list_roots(context: RequestContext[ClientSession, Any]) -> ListRootsResult | ErrorData:
        return ListRootsResult(roots=[])

    async with connect(server, list_roots_callback=list_roots) as client:
        result = await client.call_tool("count_roots", {})

    assert result == snapshot(CallToolResult(content=[TextContent(type="text", text="0")]))


@requirement("roots:list:not-supported")
async def test_list_roots_without_callback_is_error(connect: Connect) -> None:
    """A roots/list request to a client with no roots callback fails with an error the handler can observe.

    The client's default callback answers with INVALID_REQUEST rather than leaving the server
    hanging; the spec names -32601 for this case (see the divergence note on the requirement).
    """
    server = Server("rooted")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name="show_roots", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        assert name == "show_roots"
        try:
            await server.request_context.session.list_roots()
        except McpError as exc:
            return [TextContent(type="text", text=f"{exc.error.code}: {exc.error.message}")]
        raise NotImplementedError  # list_roots cannot succeed without a client callback

    async with connect(server) as client:
        result = await client.call_tool("show_roots", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(type="text", text="-32600: List roots not supported")])
    )


@requirement("roots:list:client-error")
async def test_list_roots_callback_error_surfaces_to_the_handler(connect: Connect) -> None:
    """A roots callback that answers with an error fails the roots/list request with that exact error.

    The callback's code and message reach the requesting handler verbatim as a McpError.
    """
    server = Server("rooted")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name="show_roots", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        assert name == "show_roots"
        try:
            await server.request_context.session.list_roots()
        except McpError as exc:
            return [TextContent(type="text", text=f"{exc.error.code}: {exc.error.message}")]
        raise NotImplementedError  # the callback always answers with an error

    async def list_roots(context: RequestContext[ClientSession, Any]) -> ListRootsResult | ErrorData:
        return ErrorData(code=INTERNAL_ERROR, message="roots provider crashed")

    async with connect(server, list_roots_callback=list_roots) as client:
        result = await client.call_tool("show_roots", {})

    assert result == snapshot(CallToolResult(content=[TextContent(type="text", text="-32603: roots provider crashed")]))


@requirement("roots:list-changed")
async def test_roots_list_changed_reaches_server_handler(connect: Connect) -> None:
    """A roots/list_changed notification from the client is delivered to the server's handler.

    v1's low-level `Server` exposes no decorator for this notification; the public path is direct
    assignment into `Server.notification_handlers` (a public, typed dict that the server's dispatch
    loop consults for every incoming client notification). The handler receives the notification
    object itself.

    Unlike a request, a notification has no response to await: the handler sets an event and the
    test waits on it, which is the only synchronisation point proving delivery.
    """
    delivered = anyio.Event()
    received: list[types.RootsListChangedNotification] = []

    async def on_roots_changed(notify: types.RootsListChangedNotification) -> None:
        received.append(notify)
        delivered.set()

    server = Server("rooted")
    server.notification_handlers[types.RootsListChangedNotification] = on_roots_changed

    async def list_roots(context: RequestContext[ClientSession, Any]) -> ListRootsResult | ErrorData:
        """Registered so the client declares the roots capability; the server never asks for roots."""
        raise NotImplementedError

    async with connect(server, list_roots_callback=list_roots) as client:
        await client.send_roots_list_changed()
        with anyio.fail_after(5):
            await delivered.wait()

    assert len(received) == 1
    assert received[0].method == "notifications/roots/list_changed"
