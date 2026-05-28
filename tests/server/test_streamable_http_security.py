"""Tests for StreamableHTTP server DNS rebinding protection."""

import multiprocessing
import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from multiprocessing.connection import Connection

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

SERVER_NAME = "test_streamable_http_security_server"


class SecurityTestServer(Server):  # pragma: no cover
    def __init__(self):
        super().__init__(SERVER_NAME)

    async def on_list_tools(self) -> list[Tool]:
        return []


def run_server_with_settings(
    port_writer: Connection, security_settings: TransportSecuritySettings | None = None
):  # pragma: no cover
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
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    port_writer.send(port)
    port_writer.close()

    server = uvicorn.Server(config=uvicorn.Config(app=starlette_app, log_level="error"))
    server.run(sockets=[sock])


def start_server_process(
    security_settings: TransportSecuritySettings | None = None,
) -> tuple[multiprocessing.Process, int]:
    """Start server in a separate process."""
    reader, writer = multiprocessing.Pipe(duplex=False)
    process = multiprocessing.Process(
        target=run_server_with_settings,
        kwargs={"port_writer": writer, "security_settings": security_settings},
    )
    process.start()
    writer.close()
    try:
        port = reader.recv()
    finally:
        reader.close()
    return process, port


@pytest.mark.anyio
async def test_streamable_http_security_default_settings():
    """Test StreamableHTTP with default security settings (protection enabled)."""
    process, port = start_server_process()

    try:
        # Test with valid localhost headers
        async with httpx.AsyncClient(timeout=5.0) as client:
            # POST request to initialize session
            response = await client.post(
                f"http://127.0.0.1:{port}/",
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
async def test_streamable_http_security_invalid_host_header():
    """Test StreamableHTTP with invalid Host header."""
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True)
    process, port = start_server_process(security_settings)

    try:
        # Test with invalid host header
        headers = {
            "Host": "evil.com",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://127.0.0.1:{port}/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers=headers,
            )
            assert response.status_code == 421
            assert response.text == "Invalid Host header"

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_streamable_http_security_invalid_origin_header():
    """Test StreamableHTTP with invalid Origin header."""
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"])
    process, port = start_server_process(security_settings)

    try:
        # Test with invalid origin header
        headers = {
            "Origin": "http://evil.com",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://127.0.0.1:{port}/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers=headers,
            )
            assert response.status_code == 403
            assert response.text == "Invalid Origin header"

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_streamable_http_security_invalid_content_type():
    """Test StreamableHTTP POST with invalid Content-Type header."""
    process, port = start_server_process()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Test POST with invalid content type
            response = await client.post(
                f"http://127.0.0.1:{port}/",
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
                f"http://127.0.0.1:{port}/",
                headers={"Accept": "application/json, text/event-stream"},
                content="test",
            )
            assert response.status_code == 400
            assert response.text == "Invalid Content-Type header"

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_streamable_http_security_disabled():
    """Test StreamableHTTP with security disabled."""
    settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    process, port = start_server_process(settings)

    try:
        # Test with invalid host header - should still work
        headers = {
            "Host": "evil.com",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://127.0.0.1:{port}/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers=headers,
            )
            # Should connect successfully even with invalid host
            assert response.status_code == 200

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_streamable_http_security_custom_allowed_hosts():
    """Test StreamableHTTP with custom allowed hosts."""
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost", "127.0.0.1", "custom.host"],
        allowed_origins=["http://localhost", "http://127.0.0.1", "http://custom.host"],
    )
    process, port = start_server_process(settings)

    try:
        # Test with custom allowed host
        headers = {
            "Host": "custom.host",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://127.0.0.1:{port}/",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers=headers,
            )
            # Should connect successfully with custom host
            assert response.status_code == 200
    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_streamable_http_security_get_request():
    """Test StreamableHTTP GET request with security."""
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1"])
    process, port = start_server_process(security_settings)

    try:
        # Test GET request with invalid host header
        headers = {
            "Host": "evil.com",
            "Accept": "text/event-stream",
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"http://127.0.0.1:{port}/", headers=headers)
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
            response = await client.get(f"http://127.0.0.1:{port}/", headers=headers)
            # This should pass security but fail on session validation
            assert response.status_code == 400
            body = response.json()
            assert "Missing session ID" in body["error"]["message"]

    finally:
        process.terminate()
        process.join()
