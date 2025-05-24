from collections.abc import AsyncGenerator

import anyio
import pytest

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.server.lowlevel.server import Server
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import (
    CancelledNotification,
    CancelledNotificationParams,
    ClientNotification,
    ClientRequest,
    EmptyResult,
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
        async def handle_call_tool(name: str, arguments: dict | None) -> list:
            nonlocal request_id, ev_tool_called
            if name == "slow_tool":
                request_id = server.request_context.request_id
                ev_tool_called.set()
                await anyio.sleep(10)  # Long enough to ensure we can cancel
                return []
            raise ValueError(f"Unknown tool: {name}")

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

    async def make_request(client_session):
        nonlocal ev_cancelled
        try:
            await client_session.send_request(
                ClientRequest(
                    types.CallToolRequest(
                        method="tools/call",
                        params=types.CallToolRequestParams(
                            name="slow_tool", arguments={}
                        ),
                    )
                ),
                types.CallToolResult,
            )
            pytest.fail("Request should have been cancelled")
        except McpError as e:
            # Expected - request was cancelled
            assert "Request cancelled" in str(e)
            ev_cancelled.set()

    async with create_connected_server_and_client_session(
        make_server()
    ) as client_session:
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
                        method="notifications/cancelled",
                        params=CancelledNotificationParams(requestId=request_id),
                    )
                )
            )

            # Give cancellation time to process
            with anyio.fail_after(1):
                await ev_cancelled.wait()
