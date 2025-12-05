from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import anyio
import pytest

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.server.lowlevel.server import Server
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_client_server_memory_streams, create_connected_server_and_client_session
from mcp.shared.session import BaseSession
from mcp.types import (
    CONNECTION_CLOSED,
    INTERNAL_ERROR,
    CancelledNotification,
    CancelledNotificationParams,
    ClientNotification,
    ClientRequest,
    EmptyResult,
    ErrorData,
    JSONRPCError,
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


class TestProcessResponse:
    """Tests for BaseSession._process_response static method."""

    def test_process_response_with_valid_response(self):
        """Test that a valid JSONRPCResponse is processed correctly."""
        response = JSONRPCResponse(
            jsonrpc="2.0",
            id=1,
            result={},
        )

        result = BaseSession._process_response(response, EmptyResult)

        assert isinstance(result, EmptyResult)

    def test_process_response_with_error(self):
        """Test that a JSONRPCError raises McpError."""
        error = JSONRPCError(
            jsonrpc="2.0",
            id=1,
            error=ErrorData(code=-32600, message="Invalid request"),
        )

        with pytest.raises(McpError) as exc_info:
            BaseSession._process_response(error, EmptyResult)

        assert exc_info.value.error.code == -32600
        assert exc_info.value.error.message == "Invalid request"

    def test_process_response_with_none(self):
        """
        Test defensive check for anyio fail_after race condition (#1717).

        If anyio's CancelScope incorrectly suppresses an exception during
        receive(), the response variable may never be assigned. This test
        verifies we handle this gracefully instead of raising UnboundLocalError.

        See: https://github.com/agronholm/anyio/issues/589
        """
        with pytest.raises(McpError) as exc_info:
            BaseSession._process_response(None, EmptyResult)

        assert exc_info.value.error.code == INTERNAL_ERROR
        assert "no response received" in exc_info.value.error.message


@pytest.mark.anyio
async def test_send_request_handles_end_of_stream():
    """Test that EndOfStream from response stream raises McpError with CONNECTION_CLOSED."""

    async with create_client_server_memory_streams() as (client_streams, _):
        client_read, client_write = client_streams

        async with ClientSession(read_stream=client_read, write_stream=client_write) as client_session:
            # Mock create_memory_object_stream to return a stream that raises EndOfStream
            mock_reader = AsyncMock()
            mock_reader.receive = AsyncMock(side_effect=anyio.EndOfStream)
            mock_reader.aclose = AsyncMock()

            mock_sender = AsyncMock()
            mock_sender.aclose = AsyncMock()

            # The subscripted form returns a callable that returns the tuple
            with patch("mcp.shared.session.anyio.create_memory_object_stream") as mock_create:
                # pyright: ignore[reportUnknownLambdaType]
                mock_create.__getitem__ = lambda _s, _k: lambda _z: (mock_sender, mock_reader)  # type: ignore

                with pytest.raises(McpError) as exc_info:
                    await client_session.send_request(
                        ClientRequest(types.PingRequest()),
                        EmptyResult,
                    )

                assert exc_info.value.error.code == CONNECTION_CLOSED
                assert "stream ended unexpectedly" in exc_info.value.error.message


@pytest.mark.anyio
async def test_send_request_handles_closed_resource_error():
    """Test that ClosedResourceError from response stream raises McpError with CONNECTION_CLOSED."""

    async with create_client_server_memory_streams() as (client_streams, _):
        client_read, client_write = client_streams

        async with ClientSession(read_stream=client_read, write_stream=client_write) as client_session:
            # Mock create_memory_object_stream to return a stream that raises ClosedResourceError
            mock_reader = AsyncMock()
            mock_reader.receive = AsyncMock(side_effect=anyio.ClosedResourceError)
            mock_reader.aclose = AsyncMock()

            mock_sender = AsyncMock()
            mock_sender.aclose = AsyncMock()

            # The subscripted form returns a callable that returns the tuple
            with patch("mcp.shared.session.anyio.create_memory_object_stream") as mock_create:
                # pyright: ignore[reportUnknownLambdaType]
                mock_create.__getitem__ = lambda _s, _k: lambda _z: (mock_sender, mock_reader)  # type: ignore

                with pytest.raises(McpError) as exc_info:
                    await client_session.send_request(
                        ClientRequest(types.PingRequest()),
                        EmptyResult,
                    )

                assert exc_info.value.error.code == CONNECTION_CLOSED
                assert "Connection closed" in exc_info.value.error.message
