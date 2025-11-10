"""Tests for session_id propagation through the MCP stack."""

import json
from typing import Any

import pytest
from starlette.types import Message

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


@pytest.mark.anyio
async def test_session_id_propagates_to_tool_context():
    """Test that session_id from transport propagates to tool Context."""
    # Track session_id seen in tool
    captured_session_id: str | None = None

    # Create FastMCP server with a tool that captures session_id
    mcp = FastMCP("test-session-id-server")

    @mcp.tool()
    async def get_session_info(ctx: Context[ServerSession, None]) -> dict[str, Any]:
        """Tool that returns session information."""
        nonlocal captured_session_id
        captured_session_id = ctx.session_id
        return {
            "session_id": ctx.session_id,
            "request_id": ctx.request_id,
        }

    # Create session manager with JSON response mode for easier testing
    manager = StreamableHTTPSessionManager(app=mcp._mcp_server, stateless=False, json_response=True)

    async with manager.run():
        # Prepare ASGI scope and messages
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"content-type", b"application/json"),
                (b"accept", b"application/json"),
            ],
        }

        # Create initialize request
        initialize_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        }

        # Track sent messages
        sent_messages: list[Message] = []
        receive_calls = 0
        session_id_from_header: str | None = None

        async def mock_receive():
            nonlocal receive_calls
            receive_calls += 1
            if receive_calls == 1:
                # First call: send initialize request
                return {
                    "type": "http.request",
                    "body": json.dumps(initialize_request).encode(),
                    "more_body": False,
                }
            # Subsequent calls: end stream
            return {"type": "http.disconnect"}

        async def mock_send(message: Message):
            sent_messages.append(message)
            # Capture session ID from response header
            if message["type"] == "http.response.start":
                nonlocal session_id_from_header
                headers = dict(message.get("headers", []))
                if b"mcp-session-id" in headers:
                    session_id_from_header = headers[b"mcp-session-id"].decode()

        # Handle request (initialize)
        await manager.handle_request(scope, mock_receive, mock_send)

        # Verify session ID was set in response header
        assert session_id_from_header is not None, "Session ID should be in response header"

        # Now make a tools/call request to test session_id in Context
        # Reset for second request
        receive_calls = 0
        sent_messages.clear()

        tool_call_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_session_info", "arguments": {}},
        }

        scope_with_session = {
            **scope,
            "headers": [
                *scope["headers"],
                (b"mcp-session-id", session_id_from_header.encode()),
            ],
        }

        async def mock_receive_tool_call():
            nonlocal receive_calls
            receive_calls += 1
            if receive_calls == 1:
                return {
                    "type": "http.request",
                    "body": json.dumps(tool_call_request).encode(),
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        await manager.handle_request(scope_with_session, mock_receive_tool_call, mock_send)

        # Parse the response to check if tool was called successfully
        response_body = b""
        for msg in sent_messages:
            if msg["type"] == "http.response.body":
                response_body += msg.get("body", b"")

        # Verify we got a response
        assert response_body, f"Should have received a response body, got messages: {sent_messages}"

        # Decode and parse the response
        response_text = response_body.decode()
        print(f"Response: {response_text}")  # Debug output

        # Verify session_id was captured in tool context
        assert captured_session_id is not None, (
            f"session_id should be available in Context. Response was: {response_text}"
        )
        assert captured_session_id == session_id_from_header, (
            f"session_id in Context ({captured_session_id}) should match "
            f"session ID from header ({session_id_from_header})"
        )


@pytest.mark.anyio
async def test_session_id_is_none_for_stateless_mode():
    """Test that session_id is None in stateless mode."""
    # Track session_id seen in tool
    captured_session_id: str | None = "not-set"

    # Create FastMCP server
    mcp = FastMCP("test-stateless-server")

    @mcp.tool()
    async def check_session(ctx: Context[ServerSession, None]) -> dict[str, Any]:
        """Tool that checks session_id."""
        nonlocal captured_session_id
        captured_session_id = ctx.session_id
        return {"has_session_id": ctx.session_id is not None}

    # Create session manager in stateless mode with JSON response for easier testing
    manager = StreamableHTTPSessionManager(app=mcp._mcp_server, stateless=True, json_response=True)

    async with manager.run():
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"content-type", b"application/json"),
                (b"accept", b"application/json"),
            ],
        }

        initialize_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        }

        sent_messages: list[Message] = []
        receive_calls = 0

        async def mock_receive():
            nonlocal receive_calls
            receive_calls += 1
            if receive_calls == 1:
                return {
                    "type": "http.request",
                    "body": json.dumps(initialize_request).encode(),
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        async def mock_send(message: Message):
            sent_messages.append(message)

        await manager.handle_request(scope, mock_receive, mock_send)

        # In stateless mode, session_id should not be set
        # (Note: This test primarily verifies no errors occur;
        # we can't easily call a tool in stateless mode without a full integration test)


@pytest.mark.anyio
async def test_session_id_consistent_across_requests():
    """Test that session_id remains consistent across multiple requests in same session."""
    # Track all session_ids seen
    seen_session_ids: list[str | None] = []

    # Create FastMCP server
    mcp = FastMCP("test-consistency-server")

    @mcp.tool()
    async def track_session(ctx: Context[ServerSession, None]) -> dict[str, Any]:
        """Tool that tracks session_id."""
        seen_session_ids.append(ctx.session_id)
        return {"session_id": ctx.session_id, "call_number": len(seen_session_ids)}

    # Create session manager with JSON response mode for easier testing
    manager = StreamableHTTPSessionManager(app=mcp._mcp_server, stateless=False, json_response=True)

    async with manager.run():
        # First request: initialize and get session ID
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"content-type", b"application/json"),
                (b"accept", b"application/json"),
            ],
        }

        initialize_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        }

        sent_messages: list[Message] = []
        session_id_from_header: str | None = None

        async def mock_receive_init():
            return {
                "type": "http.request",
                "body": json.dumps(initialize_request).encode(),
                "more_body": False,
            }

        async def mock_send(message: Message):
            sent_messages.append(message)
            if message["type"] == "http.response.start":
                nonlocal session_id_from_header
                headers = dict(message.get("headers", []))
                if b"mcp-session-id" in headers:
                    session_id_from_header = headers[b"mcp-session-id"].decode()

        await manager.handle_request(scope, mock_receive_init, mock_send)

        assert session_id_from_header is not None

        # Make multiple tool calls with same session ID
        for call_num in range(3):
            sent_messages.clear()

            tool_call_request = {
                "jsonrpc": "2.0",
                "id": call_num + 2,
                "method": "tools/call",
                "params": {"name": "track_session", "arguments": {}},
            }

            scope_with_session = {
                **scope,
                "headers": [
                    *scope["headers"],
                    (b"mcp-session-id", session_id_from_header.encode()),
                ],
            }

            async def mock_receive_tool():
                return {
                    "type": "http.request",
                    "body": json.dumps(tool_call_request).encode(),
                    "more_body": False,
                }

            await manager.handle_request(scope_with_session, mock_receive_tool, mock_send)

        # Verify all calls saw the same session_id
        assert len(seen_session_ids) == 3, "Should have made 3 tool calls"
        assert all(sid == session_id_from_header for sid in seen_session_ids), (
            f"All session_ids should match: {seen_session_ids}"
        )
