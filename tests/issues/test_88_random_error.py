"""Test to reproduce issue #88: Random error thrown on response."""

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import anyio
import pytest
from anyio.abc import TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp import types
from mcp.client.session import ClientSession
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import McpError
from mcp.shared.message import SessionMessage
from mcp.types import ContentBlock, TextContent


@pytest.mark.anyio
async def test_notification_validation_error(tmp_path: Path):
    """Test that timeouts are handled gracefully and don't break the server.

    This test verifies that when a client request times out:
    1. The server task stays alive
    2. The server can still handle new requests
    3. The client can make new requests
    4. No resources are leaked
    """

    server = Server(name="test")
    request_count = 0
    slow_request_lock = anyio.Event()

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="slow",
                description="A slow tool",
                inputSchema={"type": "object"},
            ),
            types.Tool(
                name="fast",
                description="A fast tool",
                inputSchema={"type": "object"},
            ),
        ]

    @server.call_tool()
    async def slow_tool(name: str, arguments: dict[str, Any]) -> Sequence[ContentBlock]:
        nonlocal request_count
        request_count += 1

        if name == "slow":
            await slow_request_lock.wait()  # it should timeout here
            return [TextContent(type="text", text=f"slow {request_count}")]
        elif name == "fast":
            return [TextContent(type="text", text=f"fast {request_count}")]
        return [TextContent(type="text", text=f"unknown {request_count}")]

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
        # Use a timeout that's:
        # - Long enough for fast operations (>10ms)
        # - Short enough for slow operations (<200ms)
        # - Not too short to avoid flakiness
        async with ClientSession(read_stream, write_stream, read_timeout_seconds=timedelta(milliseconds=50)) as session:
            await session.initialize()

            # First call should work (fast operation)
            result = await session.call_tool("fast")
            assert result.content == [TextContent(type="text", text="fast 1")]
            assert not slow_request_lock.is_set()

            # Second call should timeout (slow operation)
            with pytest.raises(McpError) as exc_info:
                await session.call_tool("slow")
            assert "Timed out while waiting" in str(exc_info.value)

            # release the slow request not to have hanging process
            slow_request_lock.set()

            # Third call should work (fast operation),
            # proving server is still responsive
            result = await session.call_tool("fast")
            assert result.content == [TextContent(type="text", text="fast 3")]
        scope.cancel()

    # Run server and client in separate task groups to avoid cancellation
    server_writer, server_reader = anyio.create_memory_object_stream[SessionMessage](1)
    client_writer, client_reader = anyio.create_memory_object_stream[SessionMessage](1)

    async with anyio.create_task_group() as tg:
        scope = await tg.start(server_handler, server_reader, client_writer)
        # Run client in a separate task to avoid cancellation
        tg.start_soon(client, client_reader, server_writer, scope)
