"""Tests for non-2xx HTTP status handling in StreamableHTTPTransport.

Verifies that when the server returns 401/403/5xx, the caller receives
a proper JSONRPCError (not a timeout).

Closes #3091
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp_types import JSONRPCError, JSONRPCRequest

from mcp.client.streamable_http import RequestContext, StreamableHTTPTransport
from mcp.shared.message import SessionMessage


class TestNon2xxStatusHandling:
    """Test that non-2xx status codes produce proper error responses."""

    def _make_request_context(self, request_id: str = "test-123") -> MagicMock:
        """Create a mock RequestContext."""
        ctx = MagicMock(spec=RequestContext)
        ctx.session_message = MagicMock()
        ctx.session_message.message = MagicMock(spec=JSONRPCRequest)
        ctx.session_message.message.id = request_id
        ctx.read_stream_writer = AsyncMock()
        ctx.client = AsyncMock()
        ctx.metadata = None
        return ctx

    def _make_transport(self) -> StreamableHTTPTransport:
        """Create a StreamableHTTPTransport for testing."""
        return StreamableHTTPTransport("http://test/mcp")

    @pytest.mark.anyio
    async def test_401_produces_error_response(self):
        """401 Unauthorized should produce a JSONRPCError with the request's ID."""
        transport = self._make_transport()

        ctx = self._make_request_context()

        # Mock the response to return 401
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.aread = AsyncMock(return_value=b"Unauthorized")

        # Mock the context manager for stream()
        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.client.stream.return_value = mock_stream_ctx

        # Call _handle_post_request
        await transport._handle_post_request(ctx)

        # Verify that an error was sent to the read_stream_writer
        ctx.read_stream_writer.send.assert_called_once()
        sent_message = ctx.read_stream_writer.send.call_args[0][0]
        assert isinstance(sent_message, SessionMessage)
        assert isinstance(sent_message.message, JSONRPCError)
        assert sent_message.message.id == "test-123"
        assert sent_message.message.error.code == -32603  # INTERNAL_ERROR

    @pytest.mark.anyio
    async def test_403_produces_error_response(self):
        """403 Forbidden should produce a JSONRPCError with the request's ID."""
        transport = self._make_transport()

        ctx = self._make_request_context()

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.aread = AsyncMock(return_value=b"Forbidden")

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.client.stream.return_value = mock_stream_ctx

        await transport._handle_post_request(ctx)

        ctx.read_stream_writer.send.assert_called_once()
        sent_message = ctx.read_stream_writer.send.call_args[0][0]
        assert isinstance(sent_message.message, JSONRPCError)
        assert sent_message.message.id == "test-123"

    @pytest.mark.anyio
    async def test_500_produces_error_response(self):
        """500 Internal Server Error should produce a JSONRPCError."""
        transport = self._make_transport()

        ctx = self._make_request_context()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.aread = AsyncMock(return_value=b"Internal Server Error")

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.client.stream.return_value = mock_stream_ctx

        await transport._handle_post_request(ctx)

        ctx.read_stream_writer.send.assert_called_once()
        sent_message = ctx.read_stream_writer.send.call_args[0][0]
        assert isinstance(sent_message.message, JSONRPCError)

    @pytest.mark.anyio
    async def test_json_error_body_is_parsed(self):
        """When server returns JSON-RPC error body, it should be used directly."""
        transport = self._make_transport()

        ctx = self._make_request_context()

        error_body = json.dumps(
            {"jsonrpc": "2.0", "id": "test-123", "error": {"code": -32600, "message": "Invalid Request"}}
        ).encode()

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.headers = {"content-type": "application/json"}
        mock_response.aread = AsyncMock(return_value=error_body)

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.client.stream.return_value = mock_stream_ctx

        await transport._handle_post_request(ctx)

        ctx.read_stream_writer.send.assert_called_once()
        sent_message = ctx.read_stream_writer.send.call_args[0][0]
        assert isinstance(sent_message.message, JSONRPCError)
        assert sent_message.message.error.code == -32600
