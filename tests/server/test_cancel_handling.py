"""Tests for request cancellation and transport-close handling."""

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
                await anyio.sleep(5)
            return CallToolResult(content=[TextContent(type="text", text=f"Call number: {call_count}")])
        raise ValueError(f"Unknown tool: {params.name}")  # pragma: no cover

    server = Server("test-server", on_list_tools=handle_list_tools, on_call_tool=handle_call_tool)

    async with Client(server, mode="legacy") as client:

        async def first_request():
            try:
                await client.session.send_request(
                    CallToolRequest(params=CallToolRequestParams(name="test_tool", arguments={})),
                    CallToolResult,
                )
                pytest.fail("First request should have been cancelled")  # pragma: no cover
            except MCPError:
                pass

        async with anyio.create_task_group() as tg:
            tg.start_soon(first_request)
            await ev_first_call.wait()

            assert first_request_id is not None
            await client.session.send_notification(
                CancelledNotification(
                    params=CancelledNotificationParams(request_id=first_request_id, reason="Testing server recovery"),
                )
            )

        result = await client.call_tool("test_tool", {})

        assert len(result.content) == 1
        content = result.content[0]
        assert content.type == "text"
        assert isinstance(content, TextContent)
        assert content.text == "Call number: 2"
        assert call_count == 2


@pytest.mark.anyio
async def test_server_cancels_in_flight_handlers_on_transport_close():
    """On transport close, server.run() must cancel in-flight handlers rather than join on them.

    Without the cancel, the task group waits for the handler, which then responds through a
    write stream _receive_loop already closed — ClosedResourceError crashes server.run().
    Drives server.run() with raw memory streams because InMemoryTransport's own
    finally-cancel masks the bug.
    """
    handler_started = anyio.Event()
    handler_cancelled = anyio.Event()
    server_run_returned = anyio.Event()

    async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        handler_started.set()
        try:
            await anyio.sleep_forever()
        finally:
            handler_cancelled.set()
        # unreachable: sleep_forever only exits via cancellation
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

            # Closing the server's input stream is what stdin EOF does.
            await to_server.aclose()

            await server_run_returned.wait()

    assert handler_cancelled.is_set()


@pytest.mark.anyio
async def test_server_handles_transport_close_with_pending_server_to_client_requests():
    """server.run() must exit cleanly when the transport closes while handlers block on server-to-client requests.

    Pins two bugs: _receive_loop's finally iterates _response_streams while woken handlers'
    send_request pops from it (RuntimeError: dictionary changed size); and the woken handler's
    MCPError is caught in _handle_request, which then respond()s on the closed write stream.
    """
    handlers_started = 0
    both_started = anyio.Event()
    server_run_returned = anyio.Event()

    async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        nonlocal handlers_started
        handlers_started += 1
        if handlers_started == 2:
            both_started.set()
        # Blocks awaiting a client response that never comes; _receive_loop's finally wakes it with CONNECTION_CLOSED.
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
            # Drain the two roots/list requests so both handlers are parked at response_stream_reader.receive().
            await from_server.receive()
            await from_server.receive()

            await to_server.aclose()

            # Without the fixes, RuntimeError or ClosedResourceError escapes run_server and this hangs.
            await server_run_returned.wait()
