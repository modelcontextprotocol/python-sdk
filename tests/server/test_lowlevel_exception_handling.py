from unittest.mock import AsyncMock, Mock

import anyio
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
@pytest.mark.parametrize(
    "error_class",
    [anyio.ClosedResourceError, anyio.BrokenResourceError],
)
async def test_exception_handling_tolerates_closed_write_stream(error_class: type[Exception]):
    """Test that _handle_message does not crash when send_log_message fails
    because the client already disconnected (write stream closed).

    Regression test for https://github.com/modelcontextprotocol/python-sdk/issues/2064
    """
    server = Server("test-server")
    session = Mock(spec=ServerSession)
    session.send_log_message = AsyncMock(side_effect=error_class())

    test_exception = RuntimeError("client disconnected mid-request")

    # Should not raise — the ClosedResourceError/BrokenResourceError from
    # send_log_message must be caught and logged, not propagated.
    await server._handle_message(test_exception, session, {}, raise_exceptions=False)

    session.send_log_message.assert_called_once()


@pytest.mark.anyio
async def test_exception_handling_closed_stream_still_reraises_when_requested():
    """Test that raise_exceptions=True still works even when the write stream is closed."""
    server = Server("test-server")
    session = Mock(spec=ServerSession)
    session.send_log_message = AsyncMock(side_effect=anyio.ClosedResourceError())

    test_exception = RuntimeError("original error")

    with pytest.raises(RuntimeError, match="original error"):
        await server._handle_message(test_exception, session, {}, raise_exceptions=True)
