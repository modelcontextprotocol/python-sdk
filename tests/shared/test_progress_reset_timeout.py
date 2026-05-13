"""Tests for reset_timeout_on_progress and max_total_timeout semantics.

Mirrors the TypeScript SDK test coverage in test/shared/protocol.test.ts.
"""

import anyio
import pytest

from mcp import types
from mcp.client.session import ClientSession
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.types import (
    JSONRPCRequest,
    JSONRPCResponse,
)


def _make_progress_notification(
    progress_token: int | str,
    progress: float,
    total: float | None = None,
) -> SessionMessage:
    """Build a raw progress notification to inject into the client's read stream."""
    from mcp.types import JSONRPCNotification

    notification = JSONRPCNotification(
        jsonrpc="2.0",
        method="notifications/progress",
        params={
            "progressToken": progress_token,
            "progress": progress,
            "total": total,
        },
    )
    return SessionMessage(message=notification)


@pytest.mark.anyio
async def test_no_progress_no_reset_timeout_fires():
    """Without progress notifications, the timeout fires normally even when
    reset_timeout_on_progress is True."""

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def mock_server():
            """Receive the request but never respond."""
            await server_read.receive()
            # Never respond — let the client timeout
            await anyio.sleep(5)

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as client_session,
        ):
            tg.start_soon(mock_server)

            with pytest.raises(MCPError) as exc_info:
                await client_session.send_request(
                    types.PingRequest(params=types.RequestParams()),
                    types.EmptyResult,
                    request_read_timeout_seconds=0.3,
                    reset_timeout_on_progress=True,
                )
            assert "Timed out" in str(exc_info.value)

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_progress_resets_timeout():
    """A progress notification received before the timeout window expires
    resets the deadline, keeping the request alive."""

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def mock_server():
            """Receive the request, send progress at ~50% of the timeout window,
            then respond after the original timeout would have expired."""
            msg = await server_read.receive()
            assert isinstance(msg.message, JSONRPCRequest)
            request_id = msg.message.id

            # Wait half the timeout, then send progress
            await anyio.sleep(0.15)
            await server_write.send(
                _make_progress_notification(progress_token=request_id, progress=0.5, total=1.0)
            )

            # Wait past the original timeout (0.3s total) so the request
            # would have timed out without the reset
            await anyio.sleep(0.25)

            # Now respond
            await server_write.send(
                SessionMessage(
                    message=JSONRPCResponse(jsonrpc="2.0", id=request_id, result={})
                )
            )

        result_holder: list[types.EmptyResult] = []

        async def make_request(client_session: ClientSession):
            result = await client_session.send_request(
                types.PingRequest(params=types.RequestParams()),
                types.EmptyResult,
                request_read_timeout_seconds=0.3,
                reset_timeout_on_progress=True,
            )
            result_holder.append(result)

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as client_session,
        ):
            tg.start_soon(mock_server)
            tg.start_soon(make_request, client_session)

            with anyio.fail_after(5):
                while not result_holder:
                    await anyio.sleep(0.05)

        assert len(result_holder) == 1
        assert isinstance(result_holder[0], types.EmptyResult)


@pytest.mark.anyio
async def test_max_total_timeout_exceeded():
    """When max_total_timeout is set and the elapsed time exceeds it, the
    request fails even though progress keeps resetting the per-window timeout."""

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def mock_server():
            """Send multiple progress notifications that keep resetting the
            per-window timeout but eventually exceed max_total_timeout."""
            msg = await server_read.receive()
            assert isinstance(msg.message, JSONRPCRequest)
            request_id = msg.message.id

            # Send progress notifications every 80ms (well within the 0.3s window)
            for i in range(5):
                await anyio.sleep(0.08)
                await server_write.send(
                    _make_progress_notification(
                        progress_token=request_id,
                        progress=float(i + 1) / 5,
                        total=1.0,
                    )
                )

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as client_session,
        ):
            tg.start_soon(mock_server)

            with pytest.raises(MCPError) as exc_info:
                await client_session.send_request(
                    types.PingRequest(params=types.RequestParams()),
                    types.EmptyResult,
                    request_read_timeout_seconds=0.3,
                    reset_timeout_on_progress=True,
                    max_total_timeout=0.35,
                )
            assert "Maximum total timeout exceeded" in str(exc_info.value)

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_progress_stops_timeout_fires():
    """When progress notifications stop arriving, the per-window timeout
    eventually fires even though reset_timeout_on_progress is enabled."""

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def mock_server():
            """Send a few progress notifications, then stop."""
            msg = await server_read.receive()
            assert isinstance(msg.message, JSONRPCRequest)
            request_id = msg.message.id

            # Send progress at 80ms and 160ms (within the 0.3s window)
            await anyio.sleep(0.08)
            await server_write.send(
                _make_progress_notification(progress_token=request_id, progress=0.3, total=1.0)
            )
            await anyio.sleep(0.08)
            await server_write.send(
                _make_progress_notification(progress_token=request_id, progress=0.6, total=1.0)
            )
            # Stop sending progress — let the client timeout after the
            # last reset window expires

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as client_session,
        ):
            tg.start_soon(mock_server)

            with pytest.raises(MCPError) as exc_info:
                await client_session.send_request(
                    types.PingRequest(params=types.RequestParams()),
                    types.EmptyResult,
                    request_read_timeout_seconds=0.3,
                    reset_timeout_on_progress=True,
                )
            assert "Timed out" in str(exc_info.value)

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_multiple_progress_notifications():
    """Multiple progress notifications each reset the timeout, keeping the
    request alive for well beyond the original timeout."""

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def mock_server():
            """Send progress every 80ms with a 0.3s timeout (3 progress
            notifications), then respond."""
            msg = await server_read.receive()
            assert isinstance(msg.message, JSONRPCRequest)
            request_id = msg.message.id

            for i in range(3):
                await anyio.sleep(0.08)
                await server_write.send(
                    _make_progress_notification(
                        progress_token=request_id,
                        progress=float(i + 1) / 3,
                        total=1.0,
                    )
                )

            # Respond after the 3rd progress
            await anyio.sleep(0.05)
            await server_write.send(
                SessionMessage(
                    message=JSONRPCResponse(jsonrpc="2.0", id=request_id, result={})
                )
            )

        result_holder: list[types.EmptyResult] = []

        async def make_request(client_session: ClientSession):
            result = await client_session.send_request(
                types.PingRequest(params=types.RequestParams()),
                types.EmptyResult,
                request_read_timeout_seconds=0.3,
                reset_timeout_on_progress=True,
            )
            result_holder.append(result)

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as client_session,
        ):
            tg.start_soon(mock_server)
            tg.start_soon(make_request, client_session)

            with anyio.fail_after(5):
                while not result_holder:
                    await anyio.sleep(0.05)

        assert len(result_holder) == 1


@pytest.mark.anyio
async def test_reset_timeout_false_by_default():
    """When reset_timeout_on_progress is False (default), progress notifications
    do NOT reset the timeout."""

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def mock_server():
            """Send progress before the timeout, then wait."""
            msg = await server_read.receive()
            assert isinstance(msg.message, JSONRPCRequest)
            request_id = msg.message.id

            # Send progress at 80ms (before the 0.3s timeout)
            await anyio.sleep(0.08)
            await server_write.send(
                _make_progress_notification(progress_token=request_id, progress=0.5, total=1.0)
            )

            # Wait past the original timeout
            await anyio.sleep(0.5)

        progress_received: list[float] = []

        async def on_progress(progress: float, total: float | None, message: str | None) -> None:
            progress_received.append(progress)

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as client_session,
        ):
            tg.start_soon(mock_server)

            with pytest.raises(MCPError) as exc_info:
                await client_session.send_request(
                    types.PingRequest(params=types.RequestParams()),
                    types.EmptyResult,
                    request_read_timeout_seconds=0.3,
                    progress_callback=on_progress,
                    reset_timeout_on_progress=False,
                )
            assert "Timed out" in str(exc_info.value)

            tg.cancel_scope.cancel()

        # Progress callback was still invoked (just didn't reset the timeout)
        assert len(progress_received) == 1


@pytest.mark.anyio
async def test_call_tool_threads_reset_timeout():
    """Verify that ClientSession.call_tool passes reset_timeout_on_progress
    through to send_request, keeping a slow tool alive via progress."""

    async def handle_call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        assert ctx.request_id is not None
        # Send progress to keep the request alive
        for i in range(3):
            await anyio.sleep(0.08)
            await ctx.session.send_progress_notification(
                progress_token=ctx.request_id,
                progress=float(i + 1) / 3,
                total=1.0,
            )
        return types.CallToolResult(content=[types.TextContent(type="text", text="done")])

    async def handle_list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="slow_tool", input_schema={})])

    server = Server(
        name="TestServer",
        on_call_tool=handle_call_tool,
        on_list_tools=handle_list_tools,
    )

    from mcp import Client

    async with Client(server) as client:
        result = await client.session.call_tool(
            "slow_tool",
            arguments={},
            read_timeout_seconds=0.3,
            reset_timeout_on_progress=True,
        )
        assert len(result.content) == 1
        text = result.content[0]
        assert isinstance(text, types.TextContent)
        assert text.text == "done"
