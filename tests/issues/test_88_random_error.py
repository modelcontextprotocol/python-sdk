"""Test to reproduce issue #88: Random error thrown on response."""

from pathlib import Path

import anyio
import mcp_types as types
import pytest
from anyio.abc import TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp_types import (
    REQUEST_TIMEOUT,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
)

from mcp.client.session import ClientSession
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.shared.message import SessionMessage


@pytest.mark.anyio
async def test_notification_validation_error(tmp_path: Path):
    """A timed-out request must not break the session: the server stays alive and later requests succeed."""

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
        assert params.name in ("slow", "fast"), f"Unknown tool: {params.name}"

        if params.name == "slow":
            # The client's timeout fires during this wait; the courtesy cancellation then interrupts it.
            await slow_request_lock.wait()
            text = f"slow {request_count}"
        else:
            text = f"fast {request_count}"
        return CallToolResult(content=[TextContent(type="text", text=text)])

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
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool("fast", read_timeout_seconds=None)
            assert result.content == [TextContent(type="text", text="fast 1")]
            assert not slow_request_lock.is_set()

            with pytest.raises(MCPError) as exc_info:
                await session.call_tool("slow", read_timeout_seconds=0.000001)  # artificial timeout that always fails
            assert exc_info.value.error.code == REQUEST_TIMEOUT

            # No-op if the courtesy cancellation already interrupted the handler.
            slow_request_lock.set()

            result = await session.call_tool("fast", read_timeout_seconds=None)
            assert result.content == [TextContent(type="text", text="fast 3")]
        scope.cancel()  # pragma: lax no cover

    server_writer, server_reader = anyio.create_memory_object_stream[SessionMessage](1)
    client_writer, client_reader = anyio.create_memory_object_stream[SessionMessage](1)

    async with anyio.create_task_group() as tg:
        scope = await tg.start(server_handler, server_reader, client_writer)
        tg.start_soon(client, client_reader, server_writer, scope)
