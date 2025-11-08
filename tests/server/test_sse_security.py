"""Tests for SSE server DNS rebinding protection."""

import logging
from collections.abc import AsyncGenerator

import anyio
import httpx
import pytest
from anyio.abc import TaskGroup
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.streaming_asgi_transport import StreamingASGITransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool
from tests.test_helpers import NoopASGI

logger = logging.getLogger(__name__)
SERVER_NAME = "test_sse_security_server"
TEST_SERVER_HOST = "testserver"
TEST_SERVER_BASE_URL = f"http://{TEST_SERVER_HOST}"


# Test server implementation
class SecurityTestServer(Server):
    def __init__(self):
        super().__init__(SERVER_NAME)

    async def on_list_tools(self) -> list[Tool]:
        return []


@pytest.fixture()
async def tg() -> AsyncGenerator[TaskGroup, None]:
    """Create a task group for the server."""
    async with anyio.create_task_group() as tg:
        try:
            yield tg
        finally:
            tg.cancel_scope.cancel()


def create_server_app_with_settings(security_settings: TransportSecuritySettings | None = None):
    """Run the SSE server with specified security settings."""
    app = SecurityTestServer()
    sse_transport = SseServerTransport("/messages/", security_settings)

    async def handle_sse(request: Request) -> NoopASGI:
        try:
            async with sse_transport.connect_sse(request.scope, request.receive, request._send) as streams:
                if streams:
                    await app.run(streams[0], streams[1], app.create_initialization_options())
        except ValueError as e:
            # Validation error was already handled inside connect_sse
            logger.debug(f"SSE connection failed validation: {e}")
        # connect_sse already responded; return a no-op ASGI endpoint
        return NoopASGI()

    routes = [
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse_transport.handle_post_message),
    ]

    starlette_app = Starlette(routes=routes)
    return starlette_app


def make_client(transport: httpx.AsyncBaseTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport, base_url=TEST_SERVER_BASE_URL, timeout=5.0)


async def close_client_streaming_response(response: httpx.Response):
    """Close the client streaming response."""
    # consume the first non-empty line / event, then stop
    async for line in response.aiter_lines():
        if line and line.strip():  # skip empty keepalive lines
            break
    # close the streaming response cleanly
    await response.aclose()


@pytest.mark.anyio
async def test_sse_security_default_settings(tg: TaskGroup):
    """Test SSE with default security settings (protection disabled)."""
    server_app = create_server_app_with_settings()
    transport = StreamingASGITransport(app=server_app, task_group=tg)

    headers = {"Host": "evil.com", "Origin": "http://evil.com"}

    async with make_client(transport) as client:
        async with client.stream("GET", "/sse", headers=headers) as response:
            assert response.status_code == 200
            await close_client_streaming_response(response)


@pytest.mark.anyio
async def test_sse_security_invalid_host_header():
    """Test SSE with invalid Host header."""
    # Enable security by providing settings with an empty allowed_hosts list
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["example.com"])
    server_app = create_server_app_with_settings(security_settings)
    transport = httpx.ASGITransport(app=server_app, raise_app_exceptions=True)

    # Test with invalid host header
    headers = {"Host": "evil.com"}

    response = await make_client(transport).get("/sse", headers=headers)
    assert response.status_code == 421
    assert response.text == "Invalid Host header"


@pytest.mark.anyio
async def test_sse_security_invalid_origin_header(tg: TaskGroup):
    """Test SSE with invalid Origin header."""
    # Configure security to allow the host but restrict origins
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=[TEST_SERVER_HOST], allowed_origins=["http://localhost:*"]
    )
    server_app = create_server_app_with_settings(security_settings)
    transport = StreamingASGITransport(app=server_app, task_group=tg)

    # Test with invalid origin header
    headers = {"Origin": "http://evil.com"}

    async with make_client(transport) as client:
        response = await client.get("/sse", headers=headers)
        assert response.status_code == 403
        assert response.text == "Invalid Origin header"


@pytest.mark.anyio
async def test_sse_security_post_invalid_content_type(tg: TaskGroup):
    """Test POST endpoint with invalid Content-Type header."""
    # Configure security to allow the host
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=[TEST_SERVER_HOST], allowed_origins=["http://127.0.0.1:*"]
    )
    server_app = create_server_app_with_settings(security_settings)
    transport = StreamingASGITransport(app=server_app, task_group=tg)

    async with make_client(transport) as client:
        # Test POST with invalid content type
        fake_session_id = "12345678123456781234567812345678"
        response = await client.post(
            f"/messages/?session_id={fake_session_id}",
            headers={"Content-Type": "text/plain"},
            content="test",
        )
        assert response.status_code == 400
        assert response.text == "Invalid Content-Type header"

        # Test POST with missing content type
        response = await client.post(f"/messages/?session_id={fake_session_id}", content="test")
        assert response.status_code == 400
        assert response.text == "Invalid Content-Type header"


@pytest.mark.anyio
async def test_sse_security_disabled(tg: TaskGroup):
    """Test SSE with security disabled."""
    settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    server_app = create_server_app_with_settings(settings)
    transport = StreamingASGITransport(app=server_app, task_group=tg)

    # Test with invalid host header - should still work
    headers = {"Host": "evil.com"}

    async with make_client(transport) as client:
        # For SSE endpoints, we need to use stream to avoid timeout
        async with client.stream("GET", "/sse", headers=headers) as response:
            # Should connect successfully even with invalid host
            assert response.status_code == 200
            await close_client_streaming_response(response)


@pytest.mark.anyio
async def test_sse_security_custom_allowed_hosts(tg: TaskGroup):
    """Test SSE with custom allowed hosts."""
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[TEST_SERVER_HOST, "custom.host"],
        allowed_origins=["http://localhost", "http://127.0.0.1", "http://custom.host"],
    )
    server_app = create_server_app_with_settings(settings)
    transport = StreamingASGITransport(app=server_app, task_group=tg)

    # Test with custom allowed host
    headers = {"Host": "custom.host"}

    async with make_client(transport) as client:
        # For SSE endpoints, we need to use stream to avoid timeout
        async with client.stream("GET", "/sse", headers=headers) as response:
            # Should connect successfully with custom host
            assert response.status_code == 200
            await close_client_streaming_response(response)

    # Test with non-allowed host
    headers = {"Host": "evil.com"}

    async with make_client(transport) as client:
        response = await client.get("/sse", headers=headers)
        assert response.status_code == 421
        assert response.text == "Invalid Host header"


@pytest.mark.anyio
async def test_sse_security_wildcard_ports(tg: TaskGroup):
    """Test SSE with wildcard port patterns."""
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[TEST_SERVER_HOST, "localhost:*", "127.0.0.1:*"],
        allowed_origins=["http://localhost:*", "http://127.0.0.1:*"],
    )
    server_app = create_server_app_with_settings(settings)
    transport = StreamingASGITransport(app=server_app, task_group=tg)

    # Test with various port numbers
    for test_port in [8080, 3000, 9999]:
        headers = {"Host": f"localhost:{test_port}"}

        async with make_client(transport) as client:
            # For SSE endpoints, we need to use stream to avoid timeout
            async with client.stream("GET", "/sse", headers=headers) as response:
                # Should connect successfully with any port
                assert response.status_code == 200
                await close_client_streaming_response(response)

        headers = {"Origin": f"http://localhost:{test_port}"}

        async with make_client(transport) as client:
            # For SSE endpoints, we need to use stream to avoid timeout
            async with client.stream("GET", "/sse", headers=headers) as response:
                # Should connect successfully with any port
                assert response.status_code == 200
                await close_client_streaming_response(response)


@pytest.mark.anyio
async def test_sse_security_post_valid_content_type(tg: TaskGroup):
    """Test POST endpoint with valid Content-Type headers."""
    # Configure security to allow the host
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[TEST_SERVER_HOST, "127.0.0.1:*"],
        allowed_origins=["http://127.0.0.1:*"],
    )
    server_app = create_server_app_with_settings(security_settings)
    transport = StreamingASGITransport(app=server_app, task_group=tg)

    async with make_client(transport) as client:
        # Test with various valid content types
        valid_content_types = [
            "application/json",
            "application/json; charset=utf-8",
            "application/json;charset=utf-8",
            "APPLICATION/JSON",  # Case insensitive
        ]

        for content_type in valid_content_types:
            # Use a valid UUID format (even though session won't exist)
            fake_session_id = "12345678123456781234567812345678"
            response = await client.post(
                f"/messages/?session_id={fake_session_id}",
                headers={"Content-Type": content_type},
                json={"test": "data"},
            )
            # Will get 404 because session doesn't exist, but that's OK
            # We're testing that it passes the content-type check
            assert response.status_code == 404
            assert response.text == "Could not find session"
