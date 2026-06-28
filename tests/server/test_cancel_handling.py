"""Test that cancelled requests don't cause double responses."""

import anyio
import pytest
from mcp_types import (
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    CancelledNotification,
    CancelledNotificationParams,
    ClientCapabilities,
    Implementation,
    InitializeRequestParams,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION

from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.shared.message import SessionMessage


@pytest.mark.anyio
async def test_server_remains_functional_after_cancel():
    """Verify server can handle new requests after a cancellation."""

    # Track tool calls
    call_count = 0
    ev_first_call = anyio.Event()
    first_request_id = None

    async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(
                    name="test_tool",
                    description="Tool for testing",
                    input_schema={"type": "object"},
                )
            ]
        )

    async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        nonlocal call_count, first_request_id
        if params.name == "test_tool":
            call_count += 1
            if call_count == 1:
                first_request_id = ctx.request_id
                ev_first_call.set()
                await anyio.sleep(5)  # First call is slow
            return CallToolResult(content=[TextContent(type="text", text=f"Call number: {call_count}")])
        raise ValueError(f"Unknown tool: {params.name}")  # pragma: no cover

    server = Server("test-server", on_list_tools=handle_list_tools, on_call_tool=handle_call_tool)

    async with Client(server, mode="legacy") as client:
        # First request (will be cancelled)
        async def first_request():
            try:
                await client.session.send_request(
                    CallToolRequest(params=CallToolRequestParams(name="test_tool", arguments={})),
                    CallToolResult,
                )
                pytest.fail("First request should have been cancelled")  # pragma: no cover
            except MCPError:
                pass  # Expected

        # Start first request
        async with anyio.create_task_group() as tg:
            tg.start_soon(first_request)

            # Wait for it to start
            await ev_first_call.wait()

            # Cancel it
            assert first_request_id is not None
            await client.session.send_notification(
                CancelledNotification(
                    params=CancelledNotificationParams(request_id=first_request_id, reason="Testing server recovery"),
                )
            )

        # Second request (should work normally)
        result = await client.call_tool("test_tool", {})

        # Verify second request completed successfully
        assert len(result.content) == 1
        # Type narrowing for pyright
        content = result.content[0]
        assert content.type == "text"
        assert isinstance(content, TextContent)
        assert content.text == "Call number: 2"
        assert call_count == 2


@pytest.mark.anyio
async def test_server_drains_in_flight_handlers_on_transport_read_eof():
    """When the transport's read side hits EOF (e.g., stdio stdin closes), the
    server must drain already-started handlers so their responses reach the
    peer via the still-open write side."""
    handler_started = anyio.Event()
    handler_allowed_to_finish = anyio.Event()
    server_run_returned = anyio.Event()

    async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        handler_started.set()
        await handler_allowed_to_finish.wait()
        return CallToolResult(content=[TextContent(type="text", text="ok")])

    server = Server("test", on_call_tool=handle_call_tool)

    to_server, server_read = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    server_write, from_server = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server():
        await server.run(
            server_read,
            server_write,
            server.create_initialization_options(),
            drain_on_read_close=True,
            read_eof_drain_timeout_seconds=None,
        )
        server_run_returned.set()

    init_req = JSONRPCRequest(
        jsonrpc="2.0",
        id=1,
        method="initialize",
        params=InitializeRequestParams(
            protocol_version=LATEST_HANDSHAKE_VERSION,
            capabilities=ClientCapabilities(),
            client_info=Implementation(name="test", version="1.0"),
        ).model_dump(by_alias=True, mode="json", exclude_none=True),
    )
    initialized = JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")
    call_req = JSONRPCRequest(
        jsonrpc="2.0",
        id=2,
        method="tools/call",
        params=CallToolRequestParams(name="slow", arguments={}).model_dump(by_alias=True, mode="json"),
    )

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg, to_server, server_read, server_write, from_server:
            tg.start_soon(run_server)

            await to_server.send(SessionMessage(init_req))
            await from_server.receive()  # init response
            await to_server.send(SessionMessage(initialized))
            await to_server.send(SessionMessage(call_req))

            await handler_started.wait()

            # Close the server's input stream — this is what stdin EOF does.
            # server.run()'s incoming_messages loop ends, finally-cancel fires,
            # handler gets CancelledError, server.run() returns.
            await to_server.aclose()

            handler_allowed_to_finish.set()

            response = await from_server.receive()
            assert isinstance(response.message, JSONRPCResponse)
            assert response.message.id == 2

            await server_run_returned.wait()


@pytest.mark.anyio
async def test_server_bounds_drain_on_read_eof_when_handler_never_finishes():
    handler_started = anyio.Event()
    handler_cancelled = anyio.Event()
    server_run_returned = anyio.Event()

    async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        handler_started.set()
        try:
            await anyio.sleep_forever()
        finally:
            handler_cancelled.set()
        raise AssertionError  # pragma: no cover

    server = Server("test", on_call_tool=handle_call_tool)

    to_server, server_read = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    server_write, from_server = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server():
        await server.run(
            server_read,
            server_write,
            server.create_initialization_options(),
            drain_on_read_close=True,
            read_eof_drain_timeout_seconds=0.05,
        )
        server_run_returned.set()

    init_req = JSONRPCRequest(
        jsonrpc="2.0",
        id=1,
        method="initialize",
        params=InitializeRequestParams(
            protocol_version=LATEST_HANDSHAKE_VERSION,
            capabilities=ClientCapabilities(),
            client_info=Implementation(name="test", version="1.0"),
        ).model_dump(by_alias=True, mode="json", exclude_none=True),
    )
    initialized = JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")
    call_req = JSONRPCRequest(
        jsonrpc="2.0",
        id=2,
        method="tools/call",
        params=CallToolRequestParams(name="slow", arguments={}).model_dump(by_alias=True, mode="json"),
    )

    with anyio.fail_after(2):
        async with anyio.create_task_group() as tg, to_server, server_read, server_write, from_server:
            tg.start_soon(run_server)

            await to_server.send(SessionMessage(init_req))
            await from_server.receive()  # init response
            await to_server.send(SessionMessage(initialized))
            await to_server.send(SessionMessage(call_req))

            await handler_started.wait()
            await to_server.aclose()

            await server_run_returned.wait()

    assert handler_cancelled.is_set()


@pytest.mark.anyio
async def test_server_reraises_handler_cancellation_when_server_is_cancelled():
    """If the server task is cancelled (e.g. KeyboardInterrupt), in-flight
    request handlers will get cancelled too. Cancellation must be re-raised so
    the task group can unwind cleanly."""
    handler_started = anyio.Event()
    server_run_returned = anyio.Event()
    cancel_scope = anyio.CancelScope()

    async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        handler_started.set()
        await anyio.sleep_forever()
        raise AssertionError  # pragma: no cover

    server = Server("test", on_call_tool=handle_call_tool)

    to_server, server_read = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    server_write, from_server = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server():
        try:
            with cancel_scope:
                await server.run(server_read, server_write, server.create_initialization_options())
        finally:
            server_run_returned.set()

    init_req = JSONRPCRequest(
        jsonrpc="2.0",
        id=1,
        method="initialize",
        params=InitializeRequestParams(
            protocol_version=LATEST_HANDSHAKE_VERSION,
            capabilities=ClientCapabilities(),
            client_info=Implementation(name="test", version="1.0"),
        ).model_dump(by_alias=True, mode="json", exclude_none=True),
    )
    initialized = JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")
    call_req = JSONRPCRequest(
        jsonrpc="2.0",
        id=2,
        method="tools/call",
        params=CallToolRequestParams(name="slow", arguments={}).model_dump(by_alias=True, mode="json"),
    )

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg, to_server, server_read, server_write, from_server:
            tg.start_soon(run_server)

            await to_server.send(SessionMessage(init_req))
            await from_server.receive()  # init response
            await to_server.send(SessionMessage(initialized))
            await to_server.send(SessionMessage(call_req))

            await handler_started.wait()
            cancel_scope.cancel()
            await server_run_returned.wait()


@pytest.mark.anyio
async def test_server_drops_response_when_write_stream_closes_mid_request():
    """If the write side closes while a handler is in-flight, responding may
    raise (ClosedResourceError/BrokenResourceError). The handler task should
    exit without crashing the server."""
    handler_started = anyio.Event()
    allow_finish = anyio.Event()
    server_run_returned = anyio.Event()

    async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        handler_started.set()
        await allow_finish.wait()
        return CallToolResult(content=[TextContent(type="text", text="ok")])

    server = Server("test", on_call_tool=handle_call_tool)

    to_server, server_read = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    server_write, from_server = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server():
        await server.run(server_read, server_write, server.create_initialization_options())
        server_run_returned.set()

    init_req = JSONRPCRequest(
        jsonrpc="2.0",
        id=1,
        method="initialize",
        params=InitializeRequestParams(
            protocol_version=LATEST_HANDSHAKE_VERSION,
            capabilities=ClientCapabilities(),
            client_info=Implementation(name="test", version="1.0"),
        ).model_dump(by_alias=True, mode="json", exclude_none=True),
    )
    initialized = JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")
    call_req = JSONRPCRequest(
        jsonrpc="2.0",
        id=2,
        method="tools/call",
        params=CallToolRequestParams(name="slow", arguments={}).model_dump(by_alias=True, mode="json"),
    )

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg, to_server, server_read, server_write, from_server:
            tg.start_soon(run_server)

            await to_server.send(SessionMessage(init_req))
            await from_server.receive()  # init response
            await to_server.send(SessionMessage(initialized))
            await to_server.send(SessionMessage(call_req))

            await handler_started.wait()
            await server_write.aclose()

            allow_finish.set()
            await to_server.aclose()

            await server_run_returned.wait()


@pytest.mark.anyio
async def test_server_handles_transport_close_with_pending_server_to_client_requests():
    """When the transport closes while handlers are blocked on server→client
    requests (sampling, roots, elicitation), server.run() must still exit cleanly.

    Two bugs covered:
      1. _receive_loop's finally iterates _response_streams with await checkpoints
         inside; the woken handler's send_request finally pops from that dict
         before the next __next__() — RuntimeError: dictionary changed size.
      2. The woken handler's MCPError is caught in _handle_request, which falls
         through to respond() against a write stream _receive_loop already closed.
    """
    handlers_started = 0
    both_started = anyio.Event()
    server_run_returned = anyio.Event()

    async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        nonlocal handlers_started
        handlers_started += 1
        if handlers_started == 2:
            both_started.set()
        # Blocks on send_request waiting for a client response that never comes.
        # _receive_loop's finally will wake this with CONNECTION_CLOSED.
        await ctx.session.list_roots()  # pyright: ignore[reportDeprecated]
        raise AssertionError  # pragma: no cover

    server = Server("test", on_call_tool=handle_call_tool)

    to_server, server_read = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    server_write, from_server = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server():
        await server.run(server_read, server_write, server.create_initialization_options())
        server_run_returned.set()

    init_req = JSONRPCRequest(
        jsonrpc="2.0",
        id=1,
        method="initialize",
        params=InitializeRequestParams(
            protocol_version=LATEST_HANDSHAKE_VERSION,
            capabilities=ClientCapabilities(),
            client_info=Implementation(name="test", version="1.0"),
        ).model_dump(by_alias=True, mode="json", exclude_none=True),
    )
    initialized = JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg, to_server, server_read, server_write, from_server:
            tg.start_soon(run_server)

            await to_server.send(SessionMessage(init_req))
            await from_server.receive()  # init response
            await to_server.send(SessionMessage(initialized))

            # Two tool calls → two handlers → two _response_streams entries.
            for rid in (2, 3):
                call_req = JSONRPCRequest(
                    jsonrpc="2.0",
                    id=rid,
                    method="tools/call",
                    params=CallToolRequestParams(name="t", arguments={}).model_dump(by_alias=True, mode="json"),
                )
                await to_server.send(SessionMessage(call_req))

            await both_started.wait()
            # Drain the two roots/list requests so send_request's _write_stream.send()
            # completes and both handlers are parked at response_stream_reader.receive().
            await from_server.receive()
            await from_server.receive()

            await to_server.aclose()

            # Without the fixes: RuntimeError (dict mutation) or ClosedResourceError
            # (respond after write-stream close) escapes run_server and this hangs.
            await server_run_returned.wait()
