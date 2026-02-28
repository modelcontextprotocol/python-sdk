from unittest.mock import AsyncMock, Mock

import pytest

from mcp import types
from mcp.server.lowlevel.server import Server
from mcp.server.session import ServerSession
from mcp.shared.session import RequestResponder


@pytest.mark.anyio
async def test_exception_handling_with_raise_exceptions_true():
    """Test that exceptions are re-raised when raise_exceptions=True"""
    server = Server("test-server")
    session = Mock(spec=ServerSession)
    session.send_log_message = AsyncMock()

    test_exception = RuntimeError("Test error")

    with pytest.raises(RuntimeError, match="Test error"):
        await server._handle_message(test_exception, session, {}, raise_exceptions=True)

    session.send_log_message.assert_called_once()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "exception_class,message",
    [
        (ValueError, "Test validation error"),
        (RuntimeError, "Test runtime error"),
        (KeyError, "Test key error"),
        (Exception, "Basic error"),
    ],
)
async def test_exception_handling_with_raise_exceptions_false(exception_class: type[Exception], message: str):
    """Test that exceptions are logged when raise_exceptions=False"""
    server = Server("test-server")
    session = Mock(spec=ServerSession)
    session.send_log_message = AsyncMock()

    test_exception = exception_class(message)

    await server._handle_message(test_exception, session, {}, raise_exceptions=False)

    # Should send log message
    session.send_log_message.assert_called_once()
    call_args = session.send_log_message.call_args

    assert call_args.kwargs["level"] == "error"
    assert call_args.kwargs["data"] == "Internal Server Error"
    assert call_args.kwargs["logger"] == "mcp.server.exception_handler"


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
async def test_exception_handling_tolerates_closed_write_stream():
    """send_log_message should not crash when the client has already disconnected."""
    import anyio

    server = Server("test-server")
    session = Mock(spec=ServerSession)
    session.send_log_message = AsyncMock(side_effect=anyio.ClosedResourceError)

    test_exception = RuntimeError("client went away")

    # Must not raise — the ClosedResourceError should be caught internally
    await server._handle_message(test_exception, session, {}, raise_exceptions=False)


@pytest.mark.anyio
async def test_exception_handling_tolerates_broken_write_stream():
    """send_log_message should not crash when the write stream is broken."""
    import anyio

    server = Server("test-server")
    session = Mock(spec=ServerSession)
    session.send_log_message = AsyncMock(side_effect=anyio.BrokenResourceError)

    test_exception = RuntimeError("client went away")

    # Must not raise — the BrokenResourceError should be caught internally
    await server._handle_message(test_exception, session, {}, raise_exceptions=False)


@pytest.mark.anyio
async def test_exception_handling_closed_stream_with_raise_exceptions():
    """Even with raise_exceptions=True, ClosedResourceError from log should be tolerated."""
    import anyio

    server = Server("test-server")
    session = Mock(spec=ServerSession)
    session.send_log_message = AsyncMock(side_effect=anyio.ClosedResourceError)

    test_exception = RuntimeError("client went away")

    # raise_exceptions re-raises the *original* exception, not the ClosedResourceError
    with pytest.raises(RuntimeError, match="client went away"):
        await server._handle_message(test_exception, session, {}, raise_exceptions=True)
