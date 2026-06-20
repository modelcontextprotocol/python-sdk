"""Cancellation interactions against the low-level Server, driven through the public Client API.

There is no client-side cancellation API: cancelling means sending a CancelledNotification
carrying the request id, which only the server-side handler can observe (`ctx.request_id`), so
these tests capture the id from inside the blocked handler before cancelling. The handler blocks
on an Event rather than a sleep, and every wait is bounded by `anyio.fail_after`.
"""

import anyio
import pytest
from inline_snapshot import snapshot

from mcp import MCPError, types
from mcp.client import ClientRequestContext, ClientSession
from mcp.server import Server, ServerRequestContext
from mcp.shared.memory import MessageStream, create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.types import (
    REQUEST_TIMEOUT,
    CallToolResult,
    EmptyResult,
    ErrorData,
    Implementation,
    InitializeResult,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    PingRequest,
    ServerCapabilities,
    TextContent,
)
from tests.interaction._connect import Connect
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("protocol:cancel:in-flight")
@requirement("protocol:cancel:handler-abort-propagates")
async def test_cancellation_stops_in_flight_handler(connect: Connect) -> None:
    """Cancelling an in-flight request interrupts its handler and fails the pending call.

    The server answers the cancelled request with an error response (the spec says it should
    not respond at all; see the divergence note on the requirement), so the caller's pending
    request raises rather than hanging.
    """
    started = anyio.Event()
    handler_cancelled = anyio.Event()
    request_ids: list[types.RequestId] = []
    errors: list[ErrorData] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "block"
        assert ctx.request_id is not None
        request_ids.append(ctx.request_id)
        started.set()
        try:
            await anyio.Event().wait()  # blocks until cancelled; nothing ever sets this event
        except anyio.get_cancelled_exc_class():
            handler_cancelled.set()
            raise
        raise NotImplementedError  # unreachable: the wait above never completes normally

    server = Server("blocker", on_call_tool=call_tool)

    async with connect(server) as client:
        with anyio.fail_after(5):
            async with anyio.create_task_group() as task_group:

                async def call_and_capture_error() -> None:
                    with pytest.raises(MCPError) as exc_info:
                        await client.call_tool("block", {})
                    errors.append(exc_info.value.error)

                task_group.start_soon(call_and_capture_error)
                await started.wait()
                await client.session.send_notification(
                    types.CancelledNotification(
                        params=types.CancelledNotificationParams(request_id=request_ids[0], reason="user aborted")
                    )
                )

            await handler_cancelled.wait()

    assert errors == snapshot([ErrorData(code=0, message="Request cancelled")])


@requirement("protocol:cancel:server-survives")
async def test_session_serves_requests_after_cancellation(connect: Connect) -> None:
    """A request cancelled mid-flight does not poison the session: the next request succeeds."""
    started = anyio.Event()
    request_ids: list[types.RequestId] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(name="block", input_schema={"type": "object"}),
                types.Tool(name="echo", input_schema={"type": "object"}),
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        if params.name == "echo":
            return CallToolResult(content=[TextContent(text="still alive")])
        assert ctx.request_id is not None
        request_ids.append(ctx.request_id)
        started.set()
        await anyio.Event().wait()  # blocks until cancelled
        raise NotImplementedError  # unreachable

    server = Server("blocker", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        with anyio.fail_after(5):
            async with anyio.create_task_group() as task_group:

                async def call_and_swallow_cancellation_error() -> None:
                    with pytest.raises(MCPError):
                        await client.call_tool("block", {})

                task_group.start_soon(call_and_swallow_cancellation_error)
                await started.wait()
                await client.session.send_notification(
                    types.CancelledNotification(params=types.CancelledNotificationParams(request_id=request_ids[0]))
                )

            result = await client.call_tool("echo", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="still alive")]))


@requirement("protocol:cancel:unknown-id-ignored")
async def test_cancellation_for_unknown_request_is_ignored(connect: Connect) -> None:
    """A cancellation referencing a request id that is not in flight is ignored without error."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="echo", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "echo"
        return CallToolResult(content=[TextContent(text="unbothered")])

    server = Server("calm", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        await client.session.send_notification(
            types.CancelledNotification(params=types.CancelledNotificationParams(request_id=9999))
        )
        result = await client.call_tool("echo", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="unbothered")]))


@requirement("protocol:cancel:server-to-client")
async def test_abandoned_server_request_cancels_the_client_callback(connect: Connect) -> None:
    """A server that abandons a sampling request cancels it, interrupting the client's callback mid-await."""
    callback_started = anyio.Event()
    callback_cancelled = anyio.Event()

    async def sampling_callback(
        context: ClientRequestContext,
        params: types.CreateMessageRequestParams,  # pyright: ignore[reportDeprecated]
    ) -> types.CreateMessageResult:  # pyright: ignore[reportDeprecated]
        callback_started.set()
        try:
            await anyio.Event().wait()  # blocks until the cancellation interrupts it
        except anyio.get_cancelled_exc_class():
            callback_cancelled.set()
            raise
        raise NotImplementedError  # unreachable

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="impatient", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "impatient"
        request = types.CreateMessageRequest(  # pyright: ignore[reportDeprecated]
            params=types.CreateMessageRequestParams(  # pyright: ignore[reportDeprecated]
                messages=[types.SamplingMessage(role="user", content=TextContent(text="Say hello."))],  # pyright: ignore[reportDeprecated]
                max_tokens=8,
            )
        )
        async with anyio.create_task_group() as abandon_scope:

            async def sample() -> None:
                await ctx.session.send_request(request, types.CreateMessageResult)  # pyright: ignore[reportDeprecated]
                raise NotImplementedError  # unreachable: the scope is cancelled

            abandon_scope.start_soon(sample)
            with anyio.fail_after(5):
                await callback_started.wait()
            abandon_scope.cancel_scope.cancel()
        with anyio.fail_after(5):
            await callback_cancelled.wait()
        return CallToolResult(content=[TextContent(text="abandoned")])

    server = Server("abandoner", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server, sampling_callback=sampling_callback) as client:
        result = await client.call_tool("impatient", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="abandoned")]))
    assert callback_cancelled.is_set()


@requirement("protocol:cancel:late-response-ignored")
async def test_a_response_for_an_unknown_request_id_is_ignored() -> None:
    """A response whose id matches no in-flight request is ignored, as the spec asks.

    The spec says a sender SHOULD ignore a response that arrives after it issued a cancellation;
    that is the same client-side code path as any response with an unknown id, and that form is
    deterministic to test without a client-side cancellation API.

    "Ignored" is proved in two halves: the pong round-trip proves the read loop survived the
    fabricated response (the ordered in-memory stream routed it first), and `surfaced` holding
    only the control notification proves the fabricated response was never delivered to
    `message_handler` (v1 surfaced it there as a RuntimeError).

    A real Server cannot be made to answer with a fabricated id, so the test plays the server's
    side of the wire by hand. Reserve this pattern for behaviour no real server can produce. The
    other tests in this file run over the transport matrix; this one is in-memory only because the
    scripted-peer mechanism is the in-memory stream pair, not because the behaviour is
    transport-specific.
    """

    async def scripted_server(streams: MessageStream) -> None:
        server_read, server_write = streams

        def respond(request_id: types.RequestId, result: types.Result) -> SessionMessage:
            return SessionMessage(
                JSONRPCResponse(
                    jsonrpc="2.0",
                    id=request_id,
                    # Serialized exactly as a real server serializes results onto the wire.
                    result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                )
            )

        init = await server_read.receive()
        assert isinstance(init, SessionMessage)
        assert isinstance(init.message, JSONRPCRequest)
        assert init.message.method == "initialize"
        await server_write.send(
            respond(
                init.message.id,
                InitializeResult(
                    protocol_version="2025-11-25",
                    capabilities=ServerCapabilities(),
                    server_info=Implementation(name="scripted", version="0.0.1"),
                ),
            )
        )

        initialized = await server_read.receive()
        assert isinstance(initialized, SessionMessage)
        assert isinstance(initialized.message, JSONRPCNotification)
        assert initialized.message.method == "notifications/initialized"

        ping = await server_read.receive()
        assert isinstance(ping, SessionMessage)
        assert isinstance(ping.message, JSONRPCRequest)
        assert ping.message.method == "ping"
        # First a fabricated id that matches nothing in flight, then a control notification that
        # is surfaced to message_handler (proving the handler is live), then the real id.
        await server_write.send(respond(9999, EmptyResult()))
        await server_write.send(
            SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/tools/list_changed"))
        )
        await server_write.send(respond(ping.message.id, EmptyResult()))

    surfaced: list[IncomingMessage] = []

    async def message_handler(message: IncomingMessage) -> None:
        surfaced.append(message)

    async with (
        create_client_server_memory_streams() as ((client_read, client_write), server_streams),
        anyio.create_task_group() as task_group,
        ClientSession(client_read, client_write, message_handler=message_handler) as session,
    ):
        task_group.start_soon(scripted_server, server_streams)
        with anyio.fail_after(5):
            await session.initialize()
            pong = await session.send_request(PingRequest(), EmptyResult)

        assert pong == snapshot(EmptyResult())
        # The stream is ordered, so the fabricated response was routed before the control
        # notification: only the control surfaced, so the unknown-id response was dropped.
        assert surfaced == snapshot([types.ToolListChangedNotification()])


@requirement("protocol:cancel:initialize-not-cancellable")
async def test_timed_out_initialize_sends_no_cancellation() -> None:
    """An abandoned initialize is not followed by notifications/cancelled on the wire (spec-mandated).

    A real Server always answers initialize, so the test plays a stalling server by hand.
    """
    received_methods: list[str] = []

    async def scripted_server(streams: MessageStream) -> None:
        server_read, server_write = streams

        # Hold the initialize request unanswered until the client's read timeout fires.
        init = await server_read.receive()
        assert isinstance(init, SessionMessage)
        assert isinstance(init.message, JSONRPCRequest)
        received_methods.append(init.message.method)

        follow_up = await server_read.receive()
        assert isinstance(follow_up, SessionMessage)
        assert isinstance(follow_up.message, JSONRPCRequest)
        received_methods.append(follow_up.message.method)
        await server_write.send(
            SessionMessage(
                JSONRPCResponse(
                    jsonrpc="2.0",
                    id=follow_up.message.id,
                    result=EmptyResult().model_dump(by_alias=True, mode="json", exclude_none=True),
                )
            )
        )

    async with (
        create_client_server_memory_streams() as ((client_read, client_write), server_streams),
        anyio.create_task_group() as task_group,
        # The session-level read timeout is the only public pathway that abandons initialize.
        ClientSession(client_read, client_write, read_timeout_seconds=0.000001) as session,
    ):
        task_group.start_soon(scripted_server, server_streams)
        with anyio.fail_after(5):
            with pytest.raises(MCPError) as exc_info:
                await session.initialize()
            assert exc_info.value.error.code == REQUEST_TIMEOUT
            # Override the session-level timeout: this ping must round-trip normally.
            pong = await session.send_request(PingRequest(), EmptyResult, request_read_timeout_seconds=5)

        assert pong == snapshot(EmptyResult())
        # The stream is ordered, so a courtesy cancel would have arrived ahead of the ping.
        assert received_methods == snapshot(["initialize", "ping"])
