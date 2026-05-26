"""Tests for StreamableHTTP server DNS rebinding protection."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool

SERVER_NAME = "test_streamable_http_security_server"


class SecurityTestServer(Server):
    def __init__(self):
        super().__init__(SERVER_NAME)

    async def on_list_tools(self) -> list[Tool]:
        return []  # pragma: no cover


def make_app(security_settings: TransportSecuritySettings | None = None) -> Starlette:
    """Build a Starlette app with the given security settings."""
    app = SecurityTestServer()
    session_manager = StreamableHTTPSessionManager(
        app=app,
        json_response=False,
        stateless=False,
        security_settings=security_settings,
    )

    async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        async with session_manager.run():
            yield

    return Starlette(routes=[Mount("/", app=handle_streamable_http)], lifespan=lifespan)


@asynccontextmanager
async def make_client(
    security_settings: TransportSecuritySettings | None = None,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create an httpx client wired to an in-process ASGI app via ASGITransport.

    StreamableHTTP POST requests return promptly (SSE body then close), so the
    ASGITransport buffering behavior is not an issue here.
    """
    app = make_app(security_settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
            yield client


@pytest.mark.anyio
async def test_streamable_http_security_default_settings():
    """Test StreamableHTTP with default security settings (protection enabled)."""
    async with make_client() as client:
        response = await client.post(
            "/",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        assert "mcp-session-id" in response.headers


@pytest.mark.anyio
async def test_streamable_http_security_invalid_host_header():
    """Test StreamableHTTP with invalid Host header."""
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True)
    async with make_client(security_settings) as client:
        response = await client.post(
            "/",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
            headers={
                "Host": "evil.com",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 421
        assert response.text == "Invalid Host header"


@pytest.mark.anyio
async def test_streamable_http_security_invalid_origin_header():
    """Test StreamableHTTP with invalid Origin header."""
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["testserver"])
    async with make_client(security_settings) as client:
        response = await client.post(
            "/",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
            headers={
                "Origin": "http://evil.com",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 403
        assert response.text == "Invalid Origin header"


@pytest.mark.anyio
async def test_streamable_http_security_invalid_content_type():
    """Test StreamableHTTP POST with invalid Content-Type header."""
    async with make_client() as client:
        # Test POST with invalid content type
        response = await client.post(
            "/",
            headers={
                "Content-Type": "text/plain",
                "Accept": "application/json, text/event-stream",
            },
            content="test",
        )
        assert response.status_code == 400
        assert response.text == "Invalid Content-Type header"

        # Test POST with missing content type
        response = await client.post(
            "/",
            headers={"Accept": "application/json, text/event-stream"},
            content="test",
        )
        assert response.status_code == 400
        assert response.text == "Invalid Content-Type header"


@pytest.mark.anyio
async def test_streamable_http_security_disabled():
    """Test StreamableHTTP with security disabled."""
    settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    async with make_client(settings) as client:
        response = await client.post(
            "/",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
            headers={
                "Host": "evil.com",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        # Should connect successfully even with invalid host
        assert response.status_code == 200


@pytest.mark.anyio
async def test_streamable_http_security_custom_allowed_hosts():
    """Test StreamableHTTP with custom allowed hosts."""
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost", "testserver", "custom.host"],
        allowed_origins=["http://localhost", "http://testserver", "http://custom.host"],
    )
    async with make_client(settings) as client:
        response = await client.post(
            "/",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
            headers={
                "Host": "custom.host",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        # Should connect successfully with custom host
        assert response.status_code == 200


@pytest.mark.anyio
async def test_streamable_http_security_get_request():
    """Test StreamableHTTP GET request with security."""
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["testserver"])
    async with make_client(security_settings) as client:
        # Test GET request with invalid host header
        response = await client.get("/", headers={"Host": "evil.com", "Accept": "text/event-stream"})
        assert response.status_code == 421
        assert response.text == "Invalid Host header"

        # Test GET request with valid host header but no session ID
        # Should pass security but fail on session validation
        response = await client.get("/", headers={"Host": "testserver", "Accept": "text/event-stream"})
        assert response.status_code == 400
        body = response.json()
        assert "Missing session ID" in body["error"]["message"]
