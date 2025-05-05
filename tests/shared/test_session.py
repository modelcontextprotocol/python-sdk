from collections.abc import AsyncGenerator

import anyio
import pytest

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.server.lowlevel.server import Server
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import (
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

    ev_tool_called = anyio.Event()
    ev_tool_cancelled = anyio.Event()
    ev_cancelled = anyio.Event()
    ev_cancel_notified = anyio.Event()

    # Start the request in a separate task so we can cancel it
    def make_server() -> Server:
        server = Server(name="TestSessionServer")

        # Register the tool handler
        @server.call_tool()
        async def handle_call_tool(name: str, arguments: dict | None) -> list:
            nonlocal ev_tool_called, ev_tool_cancelled
            if name == "slow_tool":
                ev_tool_called.set()
                with anyio.CancelScope():
                    try:
                        await anyio.sleep(10)  # Long enough to ensure we can cancel
                        return []
                    except anyio.get_cancelled_exc_class() as err:
                        ev_tool_cancelled.set()
                        raise err

            raise ValueError(f"Unknown tool: {name}")

        @server.cancel_notification()
        async def handle_cancel(requestId: str | int, reason: str | None):
            nonlocal ev_cancel_notified
            ev_cancel_notified.set()

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
            await client_session.call_tool("slow_tool")
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

            # Cancel the task via task group
            tg.cancel_scope.cancel()

            # Give cancellation time to process
            with anyio.fail_after(1):
                await ev_cancelled.wait()

            # Check server cancel notification received
            with anyio.fail_after(1):
                await ev_cancel_notified.wait()

            # Give cancellation time to process on server
            with anyio.fail_after(1):
                await ev_tool_cancelled.wait()

@pytest.mark.anyio
async def test_request_cancellation_uncancellable():
    """Test that asserts."""
    # The tool is already registered in the fixture

    ev_tool_called = anyio.Event()
    ev_tool_commplete = anyio.Event()
    ev_cancelled = anyio.Event()

    # Start the request in a separate task so we can cancel it
    def make_server() -> Server:
        server = Server(name="TestSessionServer")

        # Register the tool handler
        @server.call_tool()
        async def handle_call_tool(name: str, arguments: dict | None) -> list:
            nonlocal ev_tool_called, ev_tool_commplete
            if name == "slow_tool":
                ev_tool_called.set()
                with anyio.CancelScope():
                    with anyio.fail_after(10): # Long enough to ensure we can cancel
                        await ev_cancelled.wait()
                    ev_tool_commplete.set()
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

    async def make_request(client_session: ClientSession):
        nonlocal ev_cancelled
        try:
            await client_session.call_tool("slow_tool", cancellable=False)
        except McpError as e:
            pytest.fail("Request should not have been cancelled")

    async with create_connected_server_and_client_session(
        make_server()
    ) as client_session:
        async with anyio.create_task_group() as tg:
            tg.start_soon(make_request, client_session)

            # Wait for the request to be in-flight
            with anyio.fail_after(1):  # Timeout after 1 second
                await ev_tool_called.wait()

            # Cancel the task via task group
            tg.cancel_scope.cancel()
            ev_cancelled.set()

            # Check server completed regardless
            with anyio.fail_after(1):
                await ev_tool_commplete.wait()
