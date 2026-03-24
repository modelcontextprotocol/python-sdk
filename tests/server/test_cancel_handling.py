"""Test that cancelled requests don't cause double responses."""

from typing import Any

import anyio
import pytest

import mcp.types as types
from mcp.server.lowlevel.server import Server
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.shared.message import SessionMessage
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    CancelledNotification,
    CancelledNotificationParams,
    ClientCapabilities,
    ClientNotification,
    ClientRequest,
    Implementation,
    InitializeRequestParams,
    JSONRPCNotification,
    JSONRPCRequest,
    Tool,
)


@pytest.mark.anyio
async def test_server_remains_functional_after_cancel():
    """Verify server can handle new requests after a cancellation."""

    server = Server("test-server")

    # Track tool calls
    call_count = 0
    ev_first_call = anyio.Event()
    first_request_id = None

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return [
            Tool(
                name="test_tool",
                description="Tool for testing",
                inputSchema={},
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
        nonlocal call_count, first_request_id
        if name == "test_tool":
            call_count += 1
            if call_count == 1:
                first_request_id = server.request_context.request_id
                ev_first_call.set()
                await anyio.sleep(5)  # First call is slow
            return [types.TextContent(type="text", text=f"Call number: {call_count}")]
        raise ValueError(f"Unknown tool: {name}")  # pragma: no cover

    async with create_connected_server_and_client_session(server) as client:
        # First request (will be cancelled)
        async def first_request():
            try:
                await client.send_request(
                    ClientRequest(
                        CallToolRequest(
                            params=CallToolRequestParams(name="test_tool", arguments={}),
                        )
                    ),
                    CallToolResult,
                )
                pytest.fail("First request should have been cancelled")  # pragma: no cover
            except McpError:
                pass  # Expected

        # Start first request
        async with anyio.create_task_group() as tg:
            tg.start_soon(first_request)

            # Wait for it to start
            await ev_first_call.wait()

            # Cancel it
            assert first_request_id is not None
            await client.send_notification(
                ClientNotification(
                    CancelledNotification(
                        params=CancelledNotificationParams(
                            requestId=first_request_id,
                            reason="Testing server recovery",
                        ),
                    )
                )
            )

        # Second request (should work normally)
        result = await client.send_request(
            ClientRequest(
                CallToolRequest(
                    params=CallToolRequestParams(name="test_tool", arguments={}),
                )
            ),
            CallToolResult,
        )

        # Verify second request completed successfully
        assert len(result.content) == 1
        # Type narrowing for pyright
        content = result.content[0]
        assert content.type == "text"
        assert isinstance(content, types.TextContent)
        assert content.text == "Call number: 2"
        assert call_count == 2


@pytest.mark.anyio
async def test_server_cancels_in_flight_handlers_on_transport_close():
    """When the transport closes mid-request, server.run() must cancel in-flight
    handlers rather than join on them.

    Without the cancel, the task group waits for the handler, which then tries
    to respond through a write stream that _receive_loop already closed,
    raising ClosedResourceError and crashing server.run() with exit code 1.

    This drives server.run() with raw memory streams because InMemoryTransport
    wraps it in its own finally-cancel (_memory.py) which masks the bug.
    """
    handler_started = anyio.Event()
    handler_cancelled = anyio.Event()
    server_run_returned = anyio.Event()

    server = Server("test")

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
        handler_started.set()
        try:
            await anyio.sleep_forever()
        finally:
            handler_cancelled.set()
        # unreachable: sleep_forever only exits via cancellation
        raise AssertionError  # pragma: no cover

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
            protocolVersion=LATEST_PROTOCOL_VERSION,
            capabilities=ClientCapabilities(),
            clientInfo=Implementation(name="test", version="1.0"),
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

            await to_server.send(SessionMessage(message=types.JSONRPCMessage(init_req)))
            await from_server.receive()  # init response
            await to_server.send(SessionMessage(message=types.JSONRPCMessage(initialized)))
            await to_server.send(SessionMessage(message=types.JSONRPCMessage(call_req)))

            await handler_started.wait()

            # Close the server's input stream — this is what stdin EOF does.
            # server.run()'s incoming_messages loop ends, finally-cancel fires,
            # handler gets CancelledError, server.run() returns.
            await to_server.aclose()

            await server_run_returned.wait()

    assert handler_cancelled.is_set()


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

    server = Server("test")

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
        nonlocal handlers_started
        handlers_started += 1
        if handlers_started == 2:
            both_started.set()
        # Blocks on send_request waiting for a client response that never comes.
        # _receive_loop's finally will wake this with CONNECTION_CLOSED.
        await server.request_context.session.list_roots()
        raise AssertionError  # pragma: no cover

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
            protocolVersion=LATEST_PROTOCOL_VERSION,
            capabilities=ClientCapabilities(),
            clientInfo=Implementation(name="test", version="1.0"),
        ).model_dump(by_alias=True, mode="json", exclude_none=True),
    )
    initialized = JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg, to_server, server_read, server_write, from_server:
            tg.start_soon(run_server)

            await to_server.send(SessionMessage(message=types.JSONRPCMessage(init_req)))
            await from_server.receive()  # init response
            await to_server.send(SessionMessage(message=types.JSONRPCMessage(initialized)))

            # Two tool calls → two handlers → two _response_streams entries.
            for rid in (2, 3):
                call_req = JSONRPCRequest(
                    jsonrpc="2.0",
                    id=rid,
                    method="tools/call",
                    params=CallToolRequestParams(name="t", arguments={}).model_dump(by_alias=True, mode="json"),
                )
                await to_server.send(SessionMessage(message=types.JSONRPCMessage(call_req)))

            await both_started.wait()
            # Drain the two roots/list requests so send_request's _write_stream.send()
            # completes and both handlers are parked at response_stream_reader.receive().
            await from_server.receive()
            await from_server.receive()

            await to_server.aclose()

            # Without the fixes: RuntimeError (dict mutation) or ClosedResourceError
            # (respond after write-stream close) escapes run_server and this hangs.
            await server_run_returned.wait()
