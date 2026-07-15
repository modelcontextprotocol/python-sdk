from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

import mcp.types as types
from mcp.server.lowlevel.server import Server
from mcp.server.session import ServerSession
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
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
    responder.request = types.ClientRequest(root=types.PingRequest(method="ping"))
    responder.__enter__ = Mock(return_value=responder)
    responder.__exit__ = Mock(return_value=None)

    # Mock the _handle_request method to avoid complex setup
    server._handle_request = AsyncMock()

    # Should handle normally without any exception handling
    await server._handle_message(responder, session, {}, raise_exceptions=False)

    # Verify _handle_request was called
    server._handle_request.assert_called_once()


@pytest.mark.anyio
async def test_mcp_error_propagates_as_jsonrpc_error():
    """Test that McpError raised in a tool handler propagates as a JSON-RPC error.

    The structured error code must be preserved on the wire instead of being
    swallowed into a CallToolResult with isError=True.
    """
    server = Server("test-server")

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        raise McpError(types.ErrorData(code=-32000, message="server fault", data={"reason": "demo"}))

    async with create_connected_server_and_client_session(server) as client_session:
        await client_session.initialize()

        with pytest.raises(McpError) as exc_info:
            await client_session.call_tool("faulty_tool", {})

        error = exc_info.value.error
        assert error.code == -32000
        assert error.message == "server fault"
        assert error.data == {"reason": "demo"}


@pytest.mark.anyio
async def test_generic_exception_still_returns_error_result():
    """Test that non-McpError exceptions are still returned as isError=True results."""
    server = Server("test-server")

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        raise ValueError("Something went wrong")

    async with create_connected_server_and_client_session(server) as client_session:
        await client_session.initialize()

        result = await client_session.call_tool("failing_tool", {})

        assert result.isError is True
        assert len(result.content) == 1
        assert isinstance(result.content[0], types.TextContent)
        assert "Something went wrong" in result.content[0].text
