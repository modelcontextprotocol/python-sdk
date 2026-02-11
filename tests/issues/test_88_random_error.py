"""Test to reproduce issue #88: Random error thrown on response."""

from pathlib import Path

import anyio
import pytest
from anyio.abc import TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp import types
from mcp.client.session import ClientSession
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.shared.message import SessionMessage
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams, TextContent


@pytest.mark.anyio
async def test_notification_validation_error(tmp_path: Path):
    """Test that timeouts are handled gracefully and don't break the server.

    This test verifies that when a client request times out:
    1. The server task stays alive
    2. The server can still handle new requests
    3. The client can make new requests
    4. No resources are leaked

    Uses per-request timeouts to avoid race conditions:
    - Fast operations use no timeout (reliable in any environment)
    - Slow operations use minimal timeout (10ms) for quick test execution
    """

    request_count = 0
    slow_request_lock = anyio.Event()

    async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                types.Tool(
                    name="slow",
                    description="A slow tool",
                    input_schema={"type": "object"},
                ),
                types.Tool(
                    name="fast",
                    description="A fast tool",
                    input_schema={"type": "object"},
                ),
            ]
        )

    async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        nonlocal request_count
        request_count += 1

        if params.name == "slow":
            await slow_request_lock.wait()  # it should timeout here
            return CallToolResult(content=[TextContent(type="text", text=f"slow {request_count}")])
        elif params.name == "fast":
            return CallToolResult(content=[TextContent(type="text", text=f"fast {request_count}")])
        pytest.fail(f"Unknown tool: {params.name}")

    server = Server(name="test", on_list_tools=handle_list_tools, on_call_tool=handle_call_tool)

    async def server_handler(
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        task_status: TaskStatus[str] = anyio.TASK_STATUS_IGNORED,
    ):
        with anyio.CancelScope() as scope:
            task_status.started(scope)  # type: ignore
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
                raise_exceptions=True,
            )

    async def client(
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        scope: anyio.CancelScope,
    ):
        # No session-level timeout to avoid race conditions with fast operations
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # First call should work (fast operation, no timeout)
            result = await session.call_tool("fast", read_timeout_seconds=None)
            assert result.content == [TextContent(type="text", text="fast 1")]
            assert not slow_request_lock.is_set()

            # Second call should timeout (slow operation with minimal timeout)
            # Use very small timeout to trigger quickly without waiting
            with pytest.raises(MCPError) as exc_info:
                await session.call_tool("slow", read_timeout_seconds=0.000001)  # artificial timeout that always fails
            assert "Timed out while waiting" in str(exc_info.value)

            # release the slow request not to have hanging process
            slow_request_lock.set()

            # Third call should work (fast operation, no timeout),
            # proving server is still responsive
            result = await session.call_tool("fast", read_timeout_seconds=None)
            assert result.content == [TextContent(type="text", text="fast 3")]
        scope.cancel()  # pragma: lax no cover

    # Run server and client in separate task groups to avoid cancellation
    server_writer, server_reader = anyio.create_memory_object_stream[SessionMessage](1)
    client_writer, client_reader = anyio.create_memory_object_stream[SessionMessage](1)

    async with anyio.create_task_group() as tg:
        scope = await tg.start(server_handler, server_reader, client_writer)
        # Run client in a separate task to avoid cancellation
        tg.start_soon(client, client_reader, server_writer, scope)
