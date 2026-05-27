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
from mcp.server import Server, ServerRequestContext
from mcp.server.session import ServerSession
from mcp.shared.session import ProgressFnT
from mcp.types import CallToolResult, ProgressNotification, ProgressNotificationParams, ProgressToken, TextContent
from tests.interaction._connect import Connect
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("protocol:progress:callback")
@requirement("tools:call:progress")
async def test_progress_during_tool_call_reaches_callback_in_order(connect: Connect) -> None:
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

    async with connect(server) as client:
        result = await client.call_tool("download", {}, progress_callback=collect)

    assert result == snapshot(CallToolResult(content=[TextContent(text="downloaded")]))
    assert received == snapshot([(1.0, 3.0, "first chunk"), (2.0, 3.0, "second chunk"), (3.0, 3.0, "done")])


@requirement("protocol:progress:token-injected")
async def test_progress_token_visible_to_handler(connect: Connect) -> None:
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

    async with connect(server) as client:
        result = await client.call_tool("inspect", {}, progress_callback=ignore)

    # The token is the request id of the tools/call request itself (initialize is request 0).
    assert result == snapshot(CallToolResult(content=[TextContent(text="1")]))


@requirement("protocol:progress:no-token")
async def test_no_progress_callback_means_no_token(connect: Connect) -> None:
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

    async with connect(server) as client:
        result = await client.call_tool("inspect", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="None")]))


@requirement("protocol:progress:client-to-server")
async def test_client_progress_notification_reaches_server_handler(connect: Connect) -> None:
    """A progress notification sent by the client is delivered to the server's progress handler."""
    received: list[ProgressNotificationParams] = []
    delivered = anyio.Event()

    async def on_progress(ctx: ServerRequestContext, params: ProgressNotificationParams) -> None:
        received.append(params)
        delivered.set()

    server = Server("observer", on_progress=on_progress)

    async with connect(server) as client:
        await client.send_progress_notification("upload-1", 0.5, total=1.0, message="halfway")
        with anyio.fail_after(5):
            await delivered.wait()

    assert received == snapshot(
        [ProgressNotificationParams(progress_token="upload-1", progress=0.5, total=1.0, message="halfway")]
    )


@requirement("protocol:progress:token-unique")
async def test_concurrent_requests_carry_distinct_progress_tokens(connect: Connect) -> None:
    """Two concurrent requests carry distinct progress tokens, and each callback sees only its own progress.

    Without the barrier the first call could run to completion before the second starts, so only one
    token would be live at a time and the demultiplexing would never be exercised. The handlers each
    block until both have started and then hand control back and forth so the four progress
    notifications are emitted in strict a, b, a, b order on the wire. The two handlers send different
    progress values so a stream swap (token A delivered to callback B and vice versa) would fail: each
    callback receiving exactly its own values proves notifications are routed by token, not by arrival
    order or by chance.
    """
    progress_values = {"a": (1.0, 2.0), "b": (10.0, 20.0)}
    tokens: dict[str, ProgressToken] = {}
    entered = {"a": anyio.Event(), "b": anyio.Event()}
    # turns[n] is set to release the nth emission; each emission releases the next.
    turns = [anyio.Event() for _ in range(4)]

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="report", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "report"
        assert params.arguments is not None
        assert ctx.meta is not None
        token = ctx.meta.get("progress_token")
        assert token is not None
        label = params.arguments["label"]
        tokens[label] = token
        entered[label].set()
        # The two handlers interleave by waiting on alternating turns: a takes 0 and 2, b takes 1 and 3.
        first, second = (0, 2) if label == "a" else (1, 3)
        await turns[first].wait()
        await ctx.session.send_progress_notification(token, progress_values[label][0])
        turns[first + 1].set()
        await turns[second].wait()
        await ctx.session.send_progress_notification(token, progress_values[label][1])
        if second + 1 < len(turns):
            turns[second + 1].set()
        return CallToolResult(content=[TextContent(text="done")])

    server = Server("reporter", on_list_tools=list_tools, on_call_tool=call_tool)

    received_a: list[float] = []
    received_b: list[float] = []

    async def collect_a(progress: float, total: float | None, message: str | None) -> None:
        received_a.append(progress)

    async def collect_b(progress: float, total: float | None, message: str | None) -> None:
        received_b.append(progress)

    async with connect(server) as client:

        async def call(label: str, collect: ProgressFnT) -> None:
            await client.call_tool("report", {"label": label}, progress_callback=collect)

        with anyio.fail_after(5):
            async with anyio.create_task_group() as task_group:  # pragma: no branch
                task_group.start_soon(call, "a", collect_a)
                task_group.start_soon(call, "b", collect_b)
                await entered["a"].wait()
                await entered["b"].wait()
                turns[0].set()

    assert tokens["a"] != tokens["b"]
    assert received_a == [1.0, 2.0]
    assert received_b == [10.0, 20.0]


@requirement("protocol:progress:stops-after-completion")
@requirement("protocol:progress:late-dropped-by-client")
async def test_progress_sent_after_the_response_is_not_delivered_to_the_callback(connect: Connect) -> None:
    """A progress notification sent after the response is emitted, and the client drops it from the callback.

    This single body proves both halves: the server's `send_progress_notification` happily sends for
    a token whose request has already completed (the spec MUST that progress stops is not enforced;
    see the divergence on `stops-after-completion`), and the client, having removed the callback when
    the call returned, does not deliver the late notification to it. The message handler observes the
    late notification arriving so the test knows when to assert without polling.
    """
    captured: list[tuple[ServerSession, ProgressToken]] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="report", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "report"
        assert ctx.meta is not None
        token = ctx.meta.get("progress_token")
        assert token is not None
        captured.append((ctx.session, token))
        await ctx.session.send_progress_notification(token, 0.5)
        return CallToolResult(content=[TextContent(text="done")])

    server = Server("reporter", on_list_tools=list_tools, on_call_tool=call_tool)

    received: list[float] = []
    late_progress_arrived = anyio.Event()

    async def collect(progress: float, total: float | None, message: str | None) -> None:
        received.append(progress)

    async def message_handler(message: IncomingMessage) -> None:
        if isinstance(message, ProgressNotification) and message.params.progress == 1.0:
            late_progress_arrived.set()

    async with connect(server, message_handler=message_handler) as client:
        with anyio.fail_after(5):
            await client.call_tool("report", {}, progress_callback=collect)
            assert received == [0.5]

            server_session, token = captured[0]
            await server_session.send_progress_notification(token, 1.0)
            await late_progress_arrived.wait()

    assert received == [0.5]


@requirement("protocol:progress:monotonic")
async def test_non_increasing_progress_values_are_forwarded_unchanged(connect: Connect) -> None:
    """A handler that emits non-increasing progress values has them forwarded to the callback unchanged.

    The spec says progress MUST increase with each notification; the SDK does not enforce that on
    either side. See the divergence note on the requirement.
    """
    received: list[float] = []

    async def collect(progress: float, total: float | None, message: str | None) -> None:
        received.append(progress)

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="zigzag", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "zigzag"
        assert ctx.meta is not None
        token = ctx.meta.get("progress_token")
        assert token is not None
        await ctx.session.send_progress_notification(token, 0.5)
        await ctx.session.send_progress_notification(token, 0.3)
        await ctx.session.send_progress_notification(token, 0.9)
        return CallToolResult(content=[TextContent(text="done")])

    server = Server("zigzagger", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        await client.call_tool("zigzag", {}, progress_callback=collect)

    assert received == snapshot([0.5, 0.3, 0.9])
