from typing import Any

import anyio
import pytest

import mcp.types as types
from mcp import Client
from mcp.client.session import ClientSession
from mcp.server.lowlevel.server import Server
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import CancelledNotification, CancelledNotificationParams, EmptyResult, TextContent


@pytest.mark.anyio
async def test_in_flight_requests_cleared_after_completion():
    """Verify that _in_flight is empty after all requests complete."""
    server = Server(name="test server")
    async with Client(server) as client:
        # Send a request and wait for response
        response = await client.send_ping()
        assert isinstance(response, EmptyResult)

        # Verify _in_flight is empty
        assert len(client.session._in_flight) == 0


@pytest.mark.anyio
async def test_request_cancellation():
    """Test that requests can be cancelled while in-flight."""
    ev_tool_called = anyio.Event()
    ev_cancelled = anyio.Event()
    request_id = None

    # Create a server with a slow tool
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
                input_schema={},
            )
        ]

    async def make_request(client: Client):
        nonlocal ev_cancelled
        try:
            await client.session.send_request(
                types.CallToolRequest(
                    params=types.CallToolRequestParams(name="slow_tool", arguments={}),
                ),
                types.CallToolResult,
            )
            pytest.fail("Request should have been cancelled")  # pragma: no cover
        except McpError as e:
            # Expected - request was cancelled
            assert "Request cancelled" in str(e)
            ev_cancelled.set()

    async with Client(server) as client:
        async with anyio.create_task_group() as tg:  # pragma: no branch
            tg.start_soon(make_request, client)

            # Wait for the request to be in-flight
            with anyio.fail_after(1):  # Timeout after 1 second
                await ev_tool_called.wait()

            # Send cancellation notification
            assert request_id is not None
            await client.session.send_notification(
                CancelledNotification(params=CancelledNotificationParams(request_id=request_id))
            )

            # Give cancellation time to process
            # TODO(Marcelo): Drop the pragma once https://github.com/coveragepy/coveragepy/issues/1987 is fixed.
            with anyio.fail_after(1):  # pragma: no cover
                await ev_cancelled.wait()


@pytest.mark.anyio
async def test_connection_closed():
    """Test that pending requests are cancelled when the connection is closed remotely."""

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

            # TODO(Marcelo): Drop the pragma once https://github.com/coveragepy/coveragepy/issues/1987 is fixed.
            with anyio.fail_after(1):  # pragma: no cover
                await ev_closed.wait()
            with anyio.fail_after(1):  # pragma: no cover
                await ev_response.wait()
