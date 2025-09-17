"""Tests for StreamableHTTP server DNS rebinding protection."""

import logging
import multiprocessing
import socket
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool

logger = logging.getLogger(__name__)
SERVER_NAME = "test_streamable_http_security_server"


@pytest.fixture
def server_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url(server_port: int) -> str:
    return f"http://127.0.0.1:{server_port}"


class SecurityTestServer(Server):
    def __init__(self):
        super().__init__(SERVER_NAME)

    async def on_list_tools(self) -> list[Tool]:
        return []


def run_server_with_settings(port: int, security_settings: TransportSecuritySettings | None = None):
    """Run the StreamableHTTP server with specified security settings."""
    app = SecurityTestServer()

    # Create session manager with security settings
    session_manager = StreamableHTTPSessionManager(
        app=app,
        json_response=False,
        stateless=False,
        security_settings=security_settings,
    )

    # Create the ASGI handler
    async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    # Create Starlette app with lifespan
    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        async with session_manager.run():
            yield

    routes = [
        Mount("/", app=handle_streamable_http),
    ]

    starlette_app = Starlette(routes=routes, lifespan=lifespan)
    uvicorn.run(starlette_app, host="127.0.0.1", port=port, log_level="error")


def start_server_process(port: int, security_settings: TransportSecuritySettings | None = None):
    """Start server in a separate process."""
    process = multiprocessing.Process(target=run_server_with_settings, args=(port, security_settings))
    process.start()
    # Give server time to start
    time.sleep(1)
    return process


@pytest.mark.anyio
async def test_streamable_http_security_default_settings(server_port: int):
    """Test StreamableHTTP with default security settings (protection enabled)."""
    process = start_server_process(server_port)

    try:
        # Test with valid localhost headers
        async with httpx.AsyncClient(timeout=5.0) as client:
            # POST request to initialize session
            response = await client.post(
                f"http://127.0.0.1:{server_port}/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
            )
            assert response.status_code == 200
            assert "mcp-session-id" in response.headers

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_streamable_http_security_invalid_host_header(server_port: int):
    """Test StreamableHTTP with invalid Host header."""
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True)
    process = start_server_process(server_port, security_settings)

    try:
        # Test with invalid host header
        headers = {
            "Host": "evil.com",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://127.0.0.1:{server_port}/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers=headers,
            )
            assert response.status_code == 421
            assert response.text == "Invalid Host header"

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_streamable_http_security_invalid_origin_header(server_port: int):
    """Test StreamableHTTP with invalid Origin header."""
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"])
    process = start_server_process(server_port, security_settings)

    try:
        # Test with invalid origin header
        headers = {
            "Origin": "http://evil.com",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://127.0.0.1:{server_port}/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers=headers,
            )
            assert response.status_code == 403
            assert response.text == "Invalid Origin header"

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_streamable_http_security_invalid_content_type(server_port: int):
    """Test StreamableHTTP POST with invalid Content-Type header."""
    process = start_server_process(server_port)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Test POST with invalid content type
            response = await client.post(
                f"http://127.0.0.1:{server_port}/",
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
                f"http://127.0.0.1:{server_port}/",
                headers={"Accept": "application/json, text/event-stream"},
                content="test",
            )
            assert response.status_code == 400
            assert response.text == "Invalid Content-Type header"

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_streamable_http_security_disabled(server_port: int):
    """Test StreamableHTTP with security disabled."""
    settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    process = start_server_process(server_port, settings)

    try:
        # Test with invalid host header - should still work
        headers = {
            "Host": "evil.com",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://127.0.0.1:{server_port}/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers=headers,
            )
            # Should connect successfully even with invalid host
            assert response.status_code == 200

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_streamable_http_security_custom_allowed_hosts(server_port: int):
    """Test StreamableHTTP with custom allowed hosts."""
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost", "127.0.0.1", "custom.host"],
        allowed_origins=["http://localhost", "http://127.0.0.1", "http://custom.host"],
    )
    process = start_server_process(server_port, settings)

    try:
        # Test with custom allowed host
        headers = {
            "Host": "custom.host",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://127.0.0.1:{server_port}/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers=headers,
            )
            # Should connect successfully with custom host
            assert response.status_code == 200
    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_streamable_http_security_get_request(server_port: int):
    """Test StreamableHTTP GET request with security."""
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1"])
    process = start_server_process(server_port, security_settings)

    try:
        # Test GET request with invalid host header
        headers = {
            "Host": "evil.com",
            "Accept": "text/event-stream",
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"http://127.0.0.1:{server_port}/", headers=headers)
            assert response.status_code == 421
            assert response.text == "Invalid Host header"

        # Test GET request with valid host header
        headers = {
            "Host": "127.0.0.1",
            "Accept": "text/event-stream",
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            # GET requests need a session ID in StreamableHTTP
            # So it will fail with "Missing session ID" not security error
            response = await client.get(f"http://127.0.0.1:{server_port}/", headers=headers)
            # This should pass security but fail on session validation
            assert response.status_code == 400
            body = response.json()
            assert "Missing session ID" in body["error"]["message"]

    finally:
        process.terminate()
        process.join()
