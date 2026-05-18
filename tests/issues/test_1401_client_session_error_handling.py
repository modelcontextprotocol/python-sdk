"""Tests for issue #1401: ClientSession should propagate transport exceptions.

Root cause: _default_message_handler called anyio.checkpoint() unconditionally,
silently dropping exceptions. The async-for loop in _receive_loop then called
`continue`, waiting for the next message that never came — hanging all pending
requests indefinitely.

Fix: _default_message_handler re-raises when the message is an Exception
(transport errors from the stream). This propagates out of _receive_loop's
async-for, triggering the finally block that closes all pending response streams
with CONNECTION_CLOSED — unblocking any in-flight callers.

Protocol-level non-fatal errors (e.g. responses with unknown request IDs from
timed-out requests) are handled inline in _handle_response with a warning log,
so they do not reach _default_message_handler and cannot kill the session.
"""

import anyio
import pytest
from anyio.abc import TaskStatus

from mcp import types
from mcp.client.session import ClientSession, _default_message_handler
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.shared.message import SessionMessage
from mcp.types import CallToolRequestParams, CallToolResult, TextContent


@pytest.mark.anyio
async def test_default_message_handler_raises_on_exception():
    """_default_message_handler must re-raise Exception instances."""
    err = RuntimeError("transport failure")
    with pytest.raises(RuntimeError, match="transport failure"):
        await _default_message_handler(err)


@pytest.mark.anyio
async def test_default_message_handler_checkpoints_on_notification():
    """_default_message_handler should checkpoint (not raise) for non-exception messages."""
    notification = types.ToolListChangedNotification(method="notifications/tools/list_changed")
    # Should complete without raising
    await _default_message_handler(notification)


@pytest.mark.anyio
async def test_transport_exception_unblocks_pending_request():
    """A transport exception must unblock pending requests instead of hanging them.

    Before the fix: exception was swallowed by checkpoint(); async-for looped
    back waiting for the next message; pending call_tool hung indefinitely.

    After the fix: exception propagates out of the async-for, _receive_loop's
    finally block closes all pending response streams with CONNECTION_CLOSED,
    and call_tool raises MCPError rather than hanging.
    """
    slow_tool_started = anyio.Event()

    async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        slow_tool_started.set()
        await anyio.sleep(60)  # hangs until cancelled
        return CallToolResult(content=[TextContent(type="text", text="never")])  # pragma: no cover

    server = Server(
        name="test",
        on_call_tool=handle_call_tool,
    )

    server_writer, server_reader = anyio.create_memory_object_stream[SessionMessage](4)
    client_writer, client_reader = anyio.create_memory_object_stream[SessionMessage | Exception](4)

    call_tool_error: Exception | None = None
    server_scope: anyio.CancelScope | None = None

    async def run_server(*, task_status: TaskStatus[anyio.CancelScope]) -> None:
        with anyio.CancelScope() as scope:
            task_status.started(scope)
            await server.run(server_reader, client_writer, server.create_initialization_options())

    async def run_client() -> None:
        nonlocal call_tool_error
        async with ClientSession(client_reader, server_writer) as session:  # type: ignore[arg-type]
            await session.initialize()

            async def inject() -> None:
                await slow_tool_started.wait()
                # Inject a transport exception — simulates e.g. httpx.ReadTimeout
                await client_writer.send(RuntimeError("sse read timeout"))

            async with anyio.create_task_group() as tg:
                tg.start_soon(inject)
                try:
                    await session.call_tool("slow")
                except (MCPError, RuntimeError) as e:
                    call_tool_error = e
                    tg.cancel_scope.cancel()

        assert server_scope is not None
        server_scope.cancel()

    async with anyio.create_task_group() as tg:
        server_scope = await tg.start(run_server)
        tg.start_soon(run_client)

    assert call_tool_error is not None, "call_tool should have raised, not hung"


@pytest.mark.anyio
async def test_custom_message_handler_receives_exception():
    """A custom message_handler can intercept transport exceptions without re-raising."""
    received: list[Exception] = []

    async def capturing_handler(message: object) -> None:
        if isinstance(message, Exception):  # pragma: lax no cover
            received.append(message)  # capture — do not re-raise

    server_writer, server_reader = anyio.create_memory_object_stream[SessionMessage](4)
    client_writer, client_reader = anyio.create_memory_object_stream[SessionMessage | Exception](4)

    async with server_reader, server_writer:
        async with ClientSession(
            client_reader,  # type: ignore[arg-type]
            server_writer.clone(),
            message_handler=capturing_handler,
        ):
            await client_writer.send(ValueError("custom handler test"))
            await client_writer.aclose()
            await anyio.sleep(0.05)

    assert len(received) == 1
    assert isinstance(received[0], ValueError)
    assert str(received[0]) == "custom handler test"
