from unittest.mock import AsyncMock, Mock

import anyio
import pytest

from mcp import types
from mcp.server.lowlevel.server import Server
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder


@pytest.mark.anyio
async def test_exception_handling_with_raise_exceptions_true():
    """Transport exceptions are re-raised when raise_exceptions=True."""
    server = Server("test-server")
    session = Mock(spec=ServerSession)

    test_exception = RuntimeError("Test error")

    with pytest.raises(RuntimeError, match="Test error"):
        await server._handle_message(test_exception, session, {}, raise_exceptions=True)


@pytest.mark.anyio
async def test_exception_handling_with_raise_exceptions_false():
    """Transport exceptions are logged locally but not sent to the client.

    The transport that reported the error is likely broken; writing back
    through it races with stream closure (#1967, #2064). The TypeScript,
    Go, and C# SDKs all log locally only.
    """
    server = Server("test-server")
    session = Mock(spec=ServerSession)
    session.send_log_message = AsyncMock()

    await server._handle_message(RuntimeError("Test error"), session, {}, raise_exceptions=False)

    session.send_log_message.assert_not_called()


@pytest.mark.anyio
async def test_normal_message_handling_not_affected():
    """Test that normal messages still work correctly"""
    server = Server("test-server")
    session = Mock(spec=ServerSession)

    # Create a mock RequestResponder
    responder = Mock(spec=RequestResponder)
    responder.request = types.PingRequest(method="ping")
    responder.__enter__ = Mock(return_value=responder)
    responder.__exit__ = Mock(return_value=None)

    # Mock the _handle_request method to avoid complex setup
    server._handle_request = AsyncMock()

    # Should handle normally without any exception handling
    await server._handle_message(responder, session, {}, raise_exceptions=False)

    # Verify _handle_request was called
    server._handle_request.assert_called_once()


@pytest.mark.anyio
async def test_server_run_exits_cleanly_when_transport_yields_exception_then_closes():
    """Regression test for #1967 / #2064.

    Exercises the real Server.run() path with real memory streams, reproducing
    what happens in stateless streamable HTTP when a POST handler throws:

    1. Transport yields an Exception into the read stream
       (streamable_http.py does this in its broad POST-handler except).
    2. Transport closes the read stream (terminate() in stateless mode).
    3. _receive_loop exits its `async with read_stream, write_stream:` block,
       closing the write stream.
    4. Meanwhile _handle_message(exc) was spawned via tg.start_soon and runs
       after the write stream is closed.

    Before the fix, _handle_message tried to send_log_message through the
    closed write stream, raising ClosedResourceError inside the TaskGroup
    and crashing server.run(). After the fix, it only logs locally.
    """
    server = Server("test-server")

    read_send, read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    # Zero-buffer on the write stream forces send() to block until received.
    # With no receiver, a send() sits blocked until _receive_loop exits its
    # `async with self._read_stream, self._write_stream:` block and closes the
    # stream, at which point the blocked send raises ClosedResourceError.
    # This deterministically reproduces the race without sleeps.
    write_send, write_recv = anyio.create_memory_object_stream[SessionMessage](0)

    # What the streamable HTTP transport does: push the exception, then close.
    read_send.send_nowait(RuntimeError("simulated transport error"))
    read_send.close()

    with anyio.fail_after(5):
        # stateless=True so server.run doesn't wait for initialize handshake.
        # Before this fix, this raised ExceptionGroup(ClosedResourceError).
        await server.run(read_recv, write_send, server.create_initialization_options(), stateless=True)

    # write_send was closed inside _receive_loop's `async with`; receive_nowait
    # raises EndOfStream iff the buffer is empty (i.e., server wrote nothing).
    with pytest.raises(anyio.EndOfStream):
        write_recv.receive_nowait()
    write_recv.close()
