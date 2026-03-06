"""Tests for StreamableHTTPSessionManager."""

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import anyio
import httpx
import pytest
from starlette.types import Message

from mcp import Client, types
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext, streamable_http_manager
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER, StreamableHTTPServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.types import INVALID_REQUEST, ListToolsResult, PaginatedRequestParams


@pytest.mark.anyio
async def test_run_can_only_be_called_once():
    """Test that run() can only be called once per instance."""
    app = Server("test-server")
    manager = StreamableHTTPSessionManager(app=app)

    # First call should succeed
    async with manager.run():
        pass

    # Second call should raise RuntimeError
    with pytest.raises(RuntimeError) as excinfo:
        async with manager.run():
            pass  # pragma: no cover

    assert "StreamableHTTPSessionManager .run() can only be called once per instance" in str(excinfo.value)


@pytest.mark.anyio
async def test_run_prevents_concurrent_calls():
    """Test that concurrent calls to run() are prevented."""
    app = Server("test-server")
    manager = StreamableHTTPSessionManager(app=app)

    errors: list[Exception] = []

    async def try_run():
        try:
            async with manager.run():
                # Simulate some work
                await anyio.sleep(0.1)
        except RuntimeError as e:
            errors.append(e)

    # Try to run concurrently
    async with anyio.create_task_group() as tg:
        tg.start_soon(try_run)
        tg.start_soon(try_run)

    # One should succeed, one should fail
    assert len(errors) == 1
    assert "StreamableHTTPSessionManager .run() can only be called once per instance" in str(errors[0])


@pytest.mark.anyio
async def test_handle_request_without_run_raises_error():
    """Test that handle_request raises error if run() hasn't been called."""
    app = Server("test-server")
    manager = StreamableHTTPSessionManager(app=app)

    # Mock ASGI parameters
    scope = {"type": "http", "method": "POST", "path": "/test"}

    async def receive():  # pragma: no cover
        return {"type": "http.request", "body": b""}

    async def send(message: Message):  # pragma: no cover
        pass

    # Should raise error because run() hasn't been called
    with pytest.raises(RuntimeError) as excinfo:
        await manager.handle_request(scope, receive, send)

    assert "Task group is not initialized. Make sure to use run()." in str(excinfo.value)


class TestException(Exception):
    __test__ = False  # Prevent pytest from collecting this as a test class
    pass


@pytest.fixture
async def running_manager():
    app = Server("test-cleanup-server")
    # It's important that the app instance used by the manager is the one we can patch
    manager = StreamableHTTPSessionManager(app=app)
    async with manager.run():
        # Patch app.run here if it's simpler, or patch it within the test
        yield manager, app


@pytest.mark.anyio
async def test_stateful_session_cleanup_on_graceful_exit(running_manager: tuple[StreamableHTTPSessionManager, Server]):
    manager, app = running_manager

    mock_mcp_run = AsyncMock(return_value=None)
    # This will be called by StreamableHTTPSessionManager's run_server -> self.app.run
    app.run = mock_mcp_run

    sent_messages: list[Message] = []

    async def mock_send(message: Message):
        sent_messages.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"content-type", b"application/json")],
    }

    async def mock_receive():  # pragma: no cover
        return {"type": "http.request", "body": b"", "more_body": False}

    # Trigger session creation
    await manager.handle_request(scope, mock_receive, mock_send)

    # Extract session ID from response headers
    session_id = None
    for msg in sent_messages:  # pragma: no branch
        if msg["type"] == "http.response.start":  # pragma: no branch
            for header_name, header_value in msg.get("headers", []):  # pragma: no branch
                if header_name.decode().lower() == MCP_SESSION_ID_HEADER.lower():
                    session_id = header_value.decode()
                    break
            if session_id:  # Break outer loop if session_id is found  # pragma: no branch
                break

    assert session_id is not None, "Session ID not found in response headers"

    # Ensure MCPServer.run was called
    mock_mcp_run.assert_called_once()

    # At this point, mock_mcp_run has completed, and the finally block in
    # StreamableHTTPSessionManager's run_server should have executed.

    # To ensure the task spawned by handle_request finishes and cleanup occurs:
    # Give other tasks a chance to run. This is important for the finally block.
    await anyio.sleep(0.01)

    assert session_id not in manager._server_instances, (
        "Session ID should be removed from _server_instances after graceful exit"
    )
    assert not manager._server_instances, "No sessions should be tracked after the only session exits gracefully"


@pytest.mark.anyio
async def test_stateful_session_cleanup_on_exception(running_manager: tuple[StreamableHTTPSessionManager, Server]):
    manager, app = running_manager

    mock_mcp_run = AsyncMock(side_effect=TestException("Simulated crash"))
    app.run = mock_mcp_run

    sent_messages: list[Message] = []

    async def mock_send(message: Message):
        sent_messages.append(message)
        # If an exception occurs, the transport might try to send an error response
        # For this test, we mostly care that the session is established enough
        # to get an ID
        if message["type"] == "http.response.start" and message["status"] >= 500:  # pragma: no cover
            pass  # Expected if TestException propagates that far up the transport

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"content-type", b"application/json")],
    }

    async def mock_receive():  # pragma: no cover
        return {"type": "http.request", "body": b"", "more_body": False}

    # Trigger session creation
    await manager.handle_request(scope, mock_receive, mock_send)

    session_id = None
    for msg in sent_messages:  # pragma: no branch
        if msg["type"] == "http.response.start":  # pragma: no branch
            for header_name, header_value in msg.get("headers", []):  # pragma: no branch
                if header_name.decode().lower() == MCP_SESSION_ID_HEADER.lower():
                    session_id = header_value.decode()
                    break
            if session_id:  # Break outer loop if session_id is found  # pragma: no branch
                break

    assert session_id is not None, "Session ID not found in response headers"

    mock_mcp_run.assert_called_once()

    # Give other tasks a chance to run to ensure the finally block executes
    await anyio.sleep(0.01)

    assert session_id not in manager._server_instances, (
        "Session ID should be removed from _server_instances after an exception"
    )
    assert not manager._server_instances, "No sessions should be tracked after the only session crashes"


@pytest.mark.anyio
async def test_stateless_requests_memory_cleanup():
    """Test that stateless requests actually clean up resources using real transports."""
    app = Server("test-stateless-real-cleanup")
    manager = StreamableHTTPSessionManager(app=app, stateless=True)

    # Track created transport instances
    created_transports: list[StreamableHTTPServerTransport] = []

    # Patch StreamableHTTPServerTransport constructor to track instances

    original_constructor = StreamableHTTPServerTransport

    def track_transport(*args: Any, **kwargs: Any) -> StreamableHTTPServerTransport:
        transport = original_constructor(*args, **kwargs)
        created_transports.append(transport)
        return transport

    with patch.object(streamable_http_manager, "StreamableHTTPServerTransport", side_effect=track_transport):
        async with manager.run():
            # Mock app.run to complete immediately
            app.run = AsyncMock(return_value=None)

            # Send a simple request
            sent_messages: list[Message] = []

            async def mock_send(message: Message):
                sent_messages.append(message)

            scope = {
                "type": "http",
                "method": "POST",
                "path": "/mcp",
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"accept", b"application/json, text/event-stream"),
                ],
            }

            # Empty body to trigger early return
            async def mock_receive():
                return {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }

            # Send a request
            await manager.handle_request(scope, mock_receive, mock_send)

            # Verify transport was created
            assert len(created_transports) == 1, "Should have created one transport"

            transport = created_transports[0]

            # The key assertion - transport should be terminated
            assert transport._terminated, "Transport should be terminated after stateless request"

            # Verify internal state is cleaned up
            assert len(transport._request_streams) == 0, "Transport should have no active request streams"


@pytest.mark.anyio
async def test_unknown_session_id_returns_404(caplog: pytest.LogCaptureFixture):
    """Test that requests with unknown session IDs return HTTP 404 per MCP spec."""
    app = Server("test-unknown-session")
    manager = StreamableHTTPSessionManager(app=app)

    async with manager.run():
        sent_messages: list[Message] = []
        response_body = b""

        async def mock_send(message: Message):
            nonlocal response_body
            sent_messages.append(message)
            if message["type"] == "http.response.body":
                response_body += message.get("body", b"")

        # Request with a non-existent session ID
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"content-type", b"application/json"),
                (b"accept", b"application/json, text/event-stream"),
                (b"mcp-session-id", b"non-existent-session-id"),
            ],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}  # pragma: no cover

        with caplog.at_level(logging.INFO):
            await manager.handle_request(scope, mock_receive, mock_send)

        # Find the response start message
        response_start = next(
            (msg for msg in sent_messages if msg["type"] == "http.response.start"),
            None,
        )
        assert response_start is not None, "Should have sent a response"
        assert response_start["status"] == 404, "Should return HTTP 404 for unknown session ID"

        # Verify JSON-RPC error format
        error_data = json.loads(response_body)
        assert error_data["jsonrpc"] == "2.0"
        assert error_data["id"] is None
        assert error_data["error"]["code"] == INVALID_REQUEST
        assert error_data["error"]["message"] == "Session not found"
        assert "Rejected request with unknown or expired session ID: non-existent-session-id" in caplog.text


@pytest.mark.anyio
async def test_e2e_streamable_http_server_cleanup():
    host = "testserver"

    async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[])

    app = Server("test-server", on_list_tools=handle_list_tools)
    mcp_app = app.streamable_http_app(host=host)
    async with (
        mcp_app.router.lifespan_context(mcp_app),
        httpx.ASGITransport(mcp_app) as transport,
        httpx.AsyncClient(transport=transport) as http_client,
        Client(streamable_http_client(f"http://{host}/mcp", http_client=http_client)) as client,
    ):
        await client.list_tools()


@pytest.mark.anyio
async def test_idle_session_is_reaped():
    """After idle timeout fires, the session returns 404."""
    app = Server("test-idle-reap")
    manager = StreamableHTTPSessionManager(app=app, session_idle_timeout=0.05)

    async with manager.run():
        sent_messages: list[Message] = []

        async def mock_send(message: Message):
            sent_messages.append(message)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [(b"content-type", b"application/json")],
        }

        async def mock_receive():  # pragma: no cover
            return {"type": "http.request", "body": b"", "more_body": False}

        await manager.handle_request(scope, mock_receive, mock_send)

        session_id = None
        for msg in sent_messages:  # pragma: no branch
            if msg["type"] == "http.response.start":  # pragma: no branch
                for header_name, header_value in msg.get("headers", []):  # pragma: no branch
                    if header_name.decode().lower() == MCP_SESSION_ID_HEADER.lower():
                        session_id = header_value.decode()
                        break
                if session_id:  # pragma: no branch
                    break

        assert session_id is not None, "Session ID not found in response headers"

        # Wait for the 50ms idle timeout to fire and cleanup to complete
        await anyio.sleep(0.1)

        # Verify via public API: old session ID now returns 404
        response_messages: list[Message] = []

        async def capture_send(message: Message):
            response_messages.append(message)

        scope_with_session = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"content-type", b"application/json"),
                (b"mcp-session-id", session_id.encode()),
            ],
        }

        await manager.handle_request(scope_with_session, mock_receive, capture_send)

        response_start = next(
            (msg for msg in response_messages if msg["type"] == "http.response.start"),
            None,
        )
        assert response_start is not None
        assert response_start["status"] == 404


def test_session_idle_timeout_rejects_non_positive():
    with pytest.raises(ValueError, match="positive number"):
        StreamableHTTPSessionManager(app=Server("test"), session_idle_timeout=-1)
    with pytest.raises(ValueError, match="positive number"):
        StreamableHTTPSessionManager(app=Server("test"), session_idle_timeout=0)


def test_session_idle_timeout_rejects_stateless():
    with pytest.raises(RuntimeError, match="not supported in stateless"):
        StreamableHTTPSessionManager(app=Server("test"), session_idle_timeout=30, stateless=True)


MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

_INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0.1"},
    },
}

_INITIALIZED_NOTIFICATION = {
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
}

_TOOL_CALL_REQUEST = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {"name": "slow_tool", "arguments": {"message": "hello"}},
}


def _make_slow_tool_server() -> tuple[Server, anyio.Event]:
    """Create an MCP server with a tool that blocks forever, returning
    the server and an event that fires when the tool starts executing."""
    tool_started = anyio.Event()

    async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
        tool_started.set()
        await anyio.sleep_forever()
        return types.CallToolResult(  # pragma: no cover
            content=[types.TextContent(type="text", text="never reached")]
        )

    async def handle_list_tools(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:  # pragma: no cover
        return ListToolsResult(
            tools=[
                types.Tool(
                    name="slow_tool",
                    description="A tool that blocks forever",
                    input_schema={"type": "object", "properties": {"message": {"type": "string"}}},
                )
            ]
        )

    app = Server("test-graceful-shutdown", on_call_tool=handle_call_tool, on_list_tools=handle_list_tools)
    return app, tool_started


@pytest.mark.anyio
async def test_graceful_shutdown_terminates_active_stateless_transports():
    """Verify that shutting down the session manager terminates in-flight
    stateless transports so SSE streams close cleanly (``more_body=False``)
    instead of being abruptly cancelled.

    This prevents "upstream prematurely closed connection" errors at reverse
    proxies like nginx.
    """
    app, tool_started = _make_slow_tool_server()
    manager = StreamableHTTPSessionManager(app=app, stateless=True)

    mcp_app = StreamableHTTPASGIApp(manager)

    manager_ready = anyio.Event()
    stream_outcome: str | None = None

    with anyio.fail_after(10):
        async with anyio.create_task_group() as tg:

            async def run_lifespan_and_shutdown():
                async with manager.run():
                    manager_ready.set()
                    with anyio.fail_after(5):
                        await tool_started.wait()

            async def make_requests():
                nonlocal stream_outcome
                with anyio.fail_after(5):
                    await manager_ready.wait()
                async with (
                    httpx.ASGITransport(mcp_app) as transport,
                    httpx.AsyncClient(transport=transport, base_url="http://testserver") as client,
                ):
                    # Initialize
                    resp = await client.post("/mcp/", json=_INITIALIZE_REQUEST, headers=MCP_HEADERS)
                    resp.raise_for_status()

                    # Send initialized notification
                    resp = await client.post("/mcp/", json=_INITIALIZED_NOTIFICATION, headers=MCP_HEADERS)
                    assert resp.status_code == 202

                    # Send slow tool call — this returns an SSE stream
                    try:
                        async with client.stream(
                            "POST",
                            "/mcp/",
                            json=_TOOL_CALL_REQUEST,
                            headers=MCP_HEADERS,
                            timeout=httpx.Timeout(10, connect=5),
                        ) as stream:
                            stream.raise_for_status()
                            async for _chunk in stream.aiter_bytes():
                                pass  # pragma: no cover
                        stream_outcome = "clean"
                    except httpx.RemoteProtocolError:  # pragma: no cover
                        stream_outcome = "reset"

            tg.start_soon(run_lifespan_and_shutdown)
            tg.start_soon(make_requests)

    assert stream_outcome == "clean", f"Expected clean HTTP close, got {stream_outcome}"


@pytest.mark.anyio
async def test_graceful_shutdown_terminates_active_stateful_transports():
    """Verify that shutting down the session manager terminates in-flight
    stateful transports so SSE streams close cleanly."""
    app, tool_started = _make_slow_tool_server()
    manager = StreamableHTTPSessionManager(app=app, stateless=False)

    mcp_app = StreamableHTTPASGIApp(manager)

    manager_ready = anyio.Event()
    stream_outcome: str | None = None

    with anyio.fail_after(10):
        async with anyio.create_task_group() as tg:

            async def run_lifespan_and_shutdown():
                async with manager.run():
                    manager_ready.set()
                    with anyio.fail_after(5):
                        await tool_started.wait()

            async def make_requests():
                nonlocal stream_outcome
                with anyio.fail_after(5):
                    await manager_ready.wait()
                async with (
                    httpx.ASGITransport(mcp_app) as transport,
                    httpx.AsyncClient(transport=transport, base_url="http://testserver") as client,
                ):
                    # Initialize (creates a session)
                    resp = await client.post("/mcp/", json=_INITIALIZE_REQUEST, headers=MCP_HEADERS)
                    resp.raise_for_status()
                    session_id = resp.headers.get(MCP_SESSION_ID_HEADER)
                    assert session_id is not None

                    session_headers = {
                        **MCP_HEADERS,
                        MCP_SESSION_ID_HEADER: session_id,
                        "mcp-protocol-version": "2025-03-26",
                    }

                    # Send initialized notification
                    resp = await client.post("/mcp/", json=_INITIALIZED_NOTIFICATION, headers=session_headers)
                    assert resp.status_code == 202

                    # Send slow tool call
                    try:
                        async with client.stream(
                            "POST",
                            "/mcp/",
                            json=_TOOL_CALL_REQUEST,
                            headers=session_headers,
                            timeout=httpx.Timeout(10, connect=5),
                        ) as stream:
                            stream.raise_for_status()
                            async for _chunk in stream.aiter_bytes():
                                pass  # pragma: no cover
                        stream_outcome = "clean"
                    except httpx.RemoteProtocolError:  # pragma: no cover
                        stream_outcome = "reset"

            tg.start_soon(run_lifespan_and_shutdown)
            tg.start_soon(make_requests)

    assert stream_outcome == "clean", f"Expected clean HTTP close, got {stream_outcome}"
