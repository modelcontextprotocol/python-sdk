"""Progress interactions against the low-level Server, driven through the public Client API.

Server-to-client progress emitted during a request follows the same ordering guarantee as
logging notifications (see test_logging.py): everything the server sends before its response is
dispatched to the progress callback before the request returns, so no synchronisation is needed.
The client-to-server direction is a standalone notification with no response to await, so that
test waits on an event set by the server's handler.
"""

import anyio
import pytest
from inline_snapshot import snapshot

from mcp import types
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import CallToolResult, ProgressNotificationParams, TextContent
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("protocol:progress:callback")
@requirement("tools:call:progress")
async def test_progress_during_tool_call_reaches_callback_in_order() -> None:
    """Progress notifications emitted by a tool handler reach the caller's progress callback in order."""
    received: list[tuple[float, float | None, str | None]] = []

    async def collect(progress: float, total: float | None, message: str | None) -> None:
        received.append((progress, total, message))

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="download", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "download"
        assert ctx.meta is not None
        token = ctx.meta.get("progress_token")
        assert token is not None
        await ctx.session.send_progress_notification(token, 1.0, total=3.0, message="first chunk")
        await ctx.session.send_progress_notification(token, 2.0, total=3.0, message="second chunk")
        await ctx.session.send_progress_notification(token, 3.0, total=3.0, message="done")
        return CallToolResult(content=[TextContent(text="downloaded")])

    server = Server("downloader", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server) as client:
        result = await client.call_tool("download", {}, progress_callback=collect)

    assert result == snapshot(CallToolResult(content=[TextContent(text="downloaded")]))
    assert received == snapshot([(1.0, 3.0, "first chunk"), (2.0, 3.0, "second chunk"), (3.0, 3.0, "done")])


@requirement("protocol:progress:token-injected")
async def test_progress_token_visible_to_handler() -> None:
    """Supplying a progress callback attaches a progress token that the handler can read from the request meta."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="inspect", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "inspect"
        assert ctx.meta is not None
        return CallToolResult(content=[TextContent(text=str(ctx.meta.get("progress_token")))])

    server = Server("introspector", on_list_tools=list_tools, on_call_tool=call_tool)

    async def ignore(progress: float, total: float | None, message: str | None) -> None:
        """A progress callback that is never invoked; the tool only inspects the token."""
        raise NotImplementedError

    async with Client(server) as client:
        result = await client.call_tool("inspect", {}, progress_callback=ignore)

    # The token is the request id of the tools/call request itself (initialize is request 0).
    assert result == snapshot(CallToolResult(content=[TextContent(text="1")]))


@requirement("protocol:progress:no-token")
async def test_no_progress_callback_means_no_token() -> None:
    """Without a progress callback the request carries no progress token.

    The low-level API has no way to report request-scoped progress without a token, so a handler
    that sees no token has nothing to send progress against.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="inspect", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "inspect"
        assert ctx.meta is not None
        return CallToolResult(content=[TextContent(text=str(ctx.meta.get("progress_token")))])

    server = Server("introspector", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server) as client:
        result = await client.call_tool("inspect", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="None")]))


@requirement("protocol:progress:client-to-server")
async def test_client_progress_notification_reaches_server_handler() -> None:
    """A progress notification sent by the client is delivered to the server's progress handler."""
    received: list[ProgressNotificationParams] = []
    delivered = anyio.Event()

    async def on_progress(ctx: ServerRequestContext, params: ProgressNotificationParams) -> None:
        received.append(params)
        delivered.set()

    server = Server("observer", on_progress=on_progress)

    async with Client(server) as client:
        await client.send_progress_notification("upload-1", 0.5, total=1.0, message="halfway")
        with anyio.fail_after(5):
            await delivered.wait()

    assert received == snapshot(
        [ProgressNotificationParams(progress_token="upload-1", progress=0.5, total=1.0, message="halfway")]
    )
