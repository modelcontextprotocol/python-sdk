from collections.abc import AsyncGenerator
from typing import Any

import anyio
import pytest

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.server.lowlevel.server import Server
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_client_server_memory_streams, create_connected_server_and_client_session
from mcp.shared.message import SessionMessage
from mcp.types import (
    CancelledNotification,
    CancelledNotificationParams,
    ClientNotification,
    ClientRequest,
    EmptyResult,
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
    TextContent,
)


@pytest.fixture
def mcp_server() -> Server:
    return Server(name="test server")


@pytest.fixture
async def client_connected_to_server(
    mcp_server: Server,
) -> AsyncGenerator[ClientSession, None]:
    async with create_connected_server_and_client_session(mcp_server) as client_session:
        yield client_session


@pytest.mark.anyio
async def test_in_flight_requests_cleared_after_completion(
    client_connected_to_server: ClientSession,
):
    """Verify that _in_flight is empty after all requests complete."""
    # Send a request and wait for response
    response = await client_connected_to_server.send_ping()
    assert isinstance(response, EmptyResult)

    # Verify _in_flight is empty
    assert len(client_connected_to_server._in_flight) == 0


@pytest.mark.anyio
async def test_request_cancellation():
    """Test that requests can be cancelled while in-flight."""
    # The tool is already registered in the fixture

    ev_tool_called = anyio.Event()
    ev_cancelled = anyio.Event()
    request_id = None

    # Start the request in a separate task so we can cancel it
    def make_server() -> Server:
        server = Server(name="TestSessionServer")

        # Register the tool handler
        @server.call_tool()
        async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
            nonlocal request_id, ev_tool_called
            if name == "slow_tool":
                request_id = server.request_context.request_id
                ev_tool_called.set()
                await anyio.sleep(10)  # Long enough to ensure we can cancel
                return []  # pragma: no cover
            raise ValueError(f"Unknown tool: {name}")  # pragma: no cover

        # Register the tool so it shows up in list_tools
        @server.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            return [
                types.Tool(
                    name="slow_tool",
                    description="A slow tool that takes 10 seconds to complete",
                    inputSchema={},
                )
            ]

        return server

    async def make_request(client_session: ClientSession):
        nonlocal ev_cancelled
        try:
            await client_session.send_request(
                ClientRequest(
                    types.CallToolRequest(
                        params=types.CallToolRequestParams(name="slow_tool", arguments={}),
                    )
                ),
                types.CallToolResult,
            )
            pytest.fail("Request should have been cancelled")  # pragma: no cover
        except McpError as e:
            # Expected - request was cancelled
            assert "Request cancelled" in str(e)
            ev_cancelled.set()

    async with create_connected_server_and_client_session(make_server()) as client_session:
        async with anyio.create_task_group() as tg:
            tg.start_soon(make_request, client_session)

            # Wait for the request to be in-flight
            with anyio.fail_after(1):  # Timeout after 1 second
                await ev_tool_called.wait()

            # Send cancellation notification
            assert request_id is not None
            await client_session.send_notification(
                ClientNotification(
                    CancelledNotification(
                        params=CancelledNotificationParams(requestId=request_id),
                    )
                )
            )

            # Give cancellation time to process
            with anyio.fail_after(1):
                await ev_cancelled.wait()


@pytest.mark.anyio
async def test_response_id_type_mismatch_string_to_int():
    """
    Test that responses with string IDs are correctly matched to requests sent with
    integer IDs.

    This handles the case where a server returns "id": "0" (string) but the client
    sent "id": 0 (integer). Without ID type normalization, this would cause a timeout.
    """
    ev_response_received = anyio.Event()
    result_holder: list[types.EmptyResult] = []

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def mock_server():
            """Receive a request and respond with a string ID instead of integer."""
            message = await server_read.receive()
            assert isinstance(message, SessionMessage)
            root = message.message.root
            assert isinstance(root, JSONRPCRequest)
            # Get the original request ID (which is an integer)
            request_id = root.id
            assert isinstance(request_id, int), f"Expected int, got {type(request_id)}"

            # Respond with the ID as a string (simulating a buggy server)
            response = JSONRPCResponse(
                jsonrpc="2.0",
                id=str(request_id),  # Convert to string to simulate mismatch
                result={},
            )
            await server_write.send(SessionMessage(message=JSONRPCMessage(response)))

        async def make_request(client_session: ClientSession):
            nonlocal result_holder
            # Send a ping request (uses integer ID internally)
            result = await client_session.send_ping()
            result_holder.append(result)
            ev_response_received.set()

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as client_session,
        ):
            tg.start_soon(mock_server)
            tg.start_soon(make_request, client_session)

            with anyio.fail_after(2):
                await ev_response_received.wait()

    assert len(result_holder) == 1
    assert isinstance(result_holder[0], EmptyResult)


@pytest.mark.anyio
async def test_error_response_id_type_mismatch_string_to_int():
    """
    Test that error responses with string IDs are correctly matched to requests
    sent with integer IDs.

    This handles the case where a server returns an error with "id": "0" (string)
    but the client sent "id": 0 (integer).
    """
    ev_error_received = anyio.Event()
    error_holder: list[McpError] = []

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def mock_server():
            """Receive a request and respond with an error using a string ID."""
            message = await server_read.receive()
            assert isinstance(message, SessionMessage)
            root = message.message.root
            assert isinstance(root, JSONRPCRequest)
            request_id = root.id
            assert isinstance(request_id, int)

            # Respond with an error, using the ID as a string
            error_response = JSONRPCError(
                jsonrpc="2.0",
                id=str(request_id),  # Convert to string to simulate mismatch
                error=ErrorData(code=-32600, message="Test error"),
            )
            await server_write.send(SessionMessage(message=JSONRPCMessage(error_response)))

        async def make_request(client_session: ClientSession):
            nonlocal error_holder
            try:
                await client_session.send_ping()
                pytest.fail("Expected McpError to be raised")  # pragma: no cover
            except McpError as e:
                error_holder.append(e)
                ev_error_received.set()

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as client_session,
        ):
            tg.start_soon(mock_server)
            tg.start_soon(make_request, client_session)

            with anyio.fail_after(2):
                await ev_error_received.wait()

    assert len(error_holder) == 1
    assert "Test error" in str(error_holder[0])


@pytest.mark.anyio
async def test_response_id_non_numeric_string_no_match():
    """
    Test that responses with non-numeric string IDs don't incorrectly match
    integer request IDs.

    If a server returns "id": "abc" (non-numeric string), it should not match
    a request sent with "id": 0 (integer).
    """
    ev_timeout = anyio.Event()

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def mock_server():
            """Receive a request and respond with a non-numeric string ID."""
            message = await server_read.receive()
            assert isinstance(message, SessionMessage)

            # Respond with a non-numeric string ID (should not match)
            response = JSONRPCResponse(
                jsonrpc="2.0",
                id="not_a_number",  # Non-numeric string
                result={},
            )
            await server_write.send(SessionMessage(message=JSONRPCMessage(response)))

        async def make_request(client_session: ClientSession):
            try:
                # Use a short timeout since we expect this to fail
                from datetime import timedelta

                await client_session.send_request(
                    ClientRequest(types.PingRequest()),
                    types.EmptyResult,
                    request_read_timeout_seconds=timedelta(seconds=0.5),
                )
                pytest.fail("Expected timeout")  # pragma: no cover
            except McpError as e:
                assert "Timed out" in str(e)
                ev_timeout.set()

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as client_session,
        ):
            tg.start_soon(mock_server)
            tg.start_soon(make_request, client_session)

            with anyio.fail_after(2):
                await ev_timeout.wait()


@pytest.mark.anyio
async def test_connection_closed():
    """
    Test that pending requests are cancelled when the connection is closed remotely.
    """

    ev_closed = anyio.Event()
    ev_response = anyio.Event()

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def make_request(client_session: ClientSession):
            """Send a request in a separate task"""
            nonlocal ev_response
            try:
                # any request will do
                await client_session.initialize()
                pytest.fail("Request should have errored")  # pragma: no cover
            except McpError as e:
                # Expected - request errored
                assert "Connection closed" in str(e)
                ev_response.set()

        async def mock_server():
            """Wait for a request, then close the connection"""
            nonlocal ev_closed
            # Wait for a request
            await server_read.receive()
            # Close the connection, as if the server exited
            server_write.close()
            server_read.close()
            ev_closed.set()

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as client_session,
        ):
            tg.start_soon(make_request, client_session)
            tg.start_soon(mock_server)

            with anyio.fail_after(1):
                await ev_closed.wait()
            with anyio.fail_after(1):
                await ev_response.wait()
