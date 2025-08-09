"""Test that cancelled requests don't cause double responses."""

from typing import Any

import anyio
import pytest

import mcp.types as types
from mcp.server.lowlevel.server import Server
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    CancelledNotification,
    CancelledNotificationParams,
    ClientNotification,
    ClientRequest,
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
        raise ValueError(f"Unknown tool: {name}")

    async with create_connected_server_and_client_session(server) as client:
        # First request (will be cancelled)
        async def first_request():
            try:
                await client.send_request(
                    ClientRequest(
                        CallToolRequest(
                            method="tools/call",
                            params=CallToolRequestParams(name="test_tool", arguments={}),
                        )
                    ),
                    CallToolResult,
                )
                pytest.fail("First request should have been cancelled")
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
                        method="notifications/cancelled",
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
                    method="tools/call",
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
