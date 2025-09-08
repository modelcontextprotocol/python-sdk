"""Tests for SSE server DNS rebinding protection."""

import logging
import multiprocessing
import socket
import time

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool

logger = logging.getLogger(__name__)
SERVER_NAME = "test_sse_security_server"


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
    """Run the SSE server with specified security settings."""
    app = SecurityTestServer()
    sse_transport = SseServerTransport("/messages/", security_settings)

    async def handle_sse(request: Request):
        try:
            async with sse_transport.connect_sse(request.scope, request.receive, request._send) as streams:
                if streams:
                    await app.run(streams[0], streams[1], app.create_initialization_options())
        except ValueError as e:
            # Validation error was already handled inside connect_sse
            logger.debug(f"SSE connection failed validation: {e}")
        return Response()

    routes = [
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse_transport.handle_post_message),
    ]

    starlette_app = Starlette(routes=routes)
    uvicorn.run(starlette_app, host="127.0.0.1", port=port, log_level="error")


def start_server_process(port: int, security_settings: TransportSecuritySettings | None = None):
    """Start server in a separate process."""
    process = multiprocessing.Process(target=run_server_with_settings, args=(port, security_settings))
    process.start()
    # Give server time to start
    time.sleep(1)
    return process


@pytest.mark.anyio
async def test_sse_security_default_settings(server_port: int):
    """Test SSE with default security settings (protection disabled)."""
    process = start_server_process(server_port)

    try:
        headers = {"Host": "evil.com", "Origin": "http://evil.com"}

        async with httpx.AsyncClient(timeout=5.0) as client:
            async with client.stream("GET", f"http://127.0.0.1:{server_port}/sse", headers=headers) as response:
                assert response.status_code == 200
    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_sse_security_invalid_host_header(server_port: int):
    """Test SSE with invalid Host header."""
    # Enable security by providing settings with an empty allowed_hosts list
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["example.com"])
    process = start_server_process(server_port, security_settings)

    try:
        # Test with invalid host header
        headers = {"Host": "evil.com"}

        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://127.0.0.1:{server_port}/sse", headers=headers)
            assert response.status_code == 421
            assert response.text == "Invalid Host header"

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_sse_security_invalid_origin_header(server_port: int):
    """Test SSE with invalid Origin header."""
    # Configure security to allow the host but restrict origins
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"], allowed_origins=["http://localhost:*"]
    )
    process = start_server_process(server_port, security_settings)

    try:
        # Test with invalid origin header
        headers = {"Origin": "http://evil.com"}

        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://127.0.0.1:{server_port}/sse", headers=headers)
            assert response.status_code == 403
            assert response.text == "Invalid Origin header"

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_sse_security_post_invalid_content_type(server_port: int):
    """Test POST endpoint with invalid Content-Type header."""
    # Configure security to allow the host
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"], allowed_origins=["http://127.0.0.1:*"]
    )
    process = start_server_process(server_port, security_settings)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Test POST with invalid content type
            fake_session_id = "12345678123456781234567812345678"
            response = await client.post(
                f"http://127.0.0.1:{server_port}/messages/?session_id={fake_session_id}",
                headers={"Content-Type": "text/plain"},
                content="test",
            )
            assert response.status_code == 400
            assert response.text == "Invalid Content-Type header"

            # Test POST with missing content type
            response = await client.post(
                f"http://127.0.0.1:{server_port}/messages/?session_id={fake_session_id}", content="test"
            )
            assert response.status_code == 400
            assert response.text == "Invalid Content-Type header"

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_sse_security_disabled(server_port: int):
    """Test SSE with security disabled."""
    settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    process = start_server_process(server_port, settings)

    try:
        # Test with invalid host header - should still work
        headers = {"Host": "evil.com"}

        async with httpx.AsyncClient(timeout=5.0) as client:
            # For SSE endpoints, we need to use stream to avoid timeout
            async with client.stream("GET", f"http://127.0.0.1:{server_port}/sse", headers=headers) as response:
                # Should connect successfully even with invalid host
                assert response.status_code == 200

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_sse_security_custom_allowed_hosts(server_port: int):
    """Test SSE with custom allowed hosts."""
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost", "127.0.0.1", "custom.host"],
        allowed_origins=["http://localhost", "http://127.0.0.1", "http://custom.host"],
    )
    process = start_server_process(server_port, settings)

    try:
        # Test with custom allowed host
        headers = {"Host": "custom.host"}

        async with httpx.AsyncClient(timeout=5.0) as client:
            # For SSE endpoints, we need to use stream to avoid timeout
            async with client.stream("GET", f"http://127.0.0.1:{server_port}/sse", headers=headers) as response:
                # Should connect successfully with custom host
                assert response.status_code == 200

        # Test with non-allowed host
        headers = {"Host": "evil.com"}

        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://127.0.0.1:{server_port}/sse", headers=headers)
            assert response.status_code == 421
            assert response.text == "Invalid Host header"

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_sse_security_wildcard_ports(server_port: int):
    """Test SSE with wildcard port patterns."""
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost:*", "127.0.0.1:*"],
        allowed_origins=["http://localhost:*", "http://127.0.0.1:*"],
    )
    process = start_server_process(server_port, settings)

    try:
        # Test with various port numbers
        for test_port in [8080, 3000, 9999]:
            headers = {"Host": f"localhost:{test_port}"}

            async with httpx.AsyncClient(timeout=5.0) as client:
                # For SSE endpoints, we need to use stream to avoid timeout
                async with client.stream("GET", f"http://127.0.0.1:{server_port}/sse", headers=headers) as response:
                    # Should connect successfully with any port
                    assert response.status_code == 200

            headers = {"Origin": f"http://localhost:{test_port}"}

            async with httpx.AsyncClient(timeout=5.0) as client:
                # For SSE endpoints, we need to use stream to avoid timeout
                async with client.stream("GET", f"http://127.0.0.1:{server_port}/sse", headers=headers) as response:
                    # Should connect successfully with any port
                    assert response.status_code == 200

    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_sse_security_post_valid_content_type(server_port: int):
    """Test POST endpoint with valid Content-Type headers."""
    # Configure security to allow the host
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"], allowed_origins=["http://127.0.0.1:*"]
    )
    process = start_server_process(server_port, security_settings)

    try:
        async with httpx.AsyncClient() as client:
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
                    f"http://127.0.0.1:{server_port}/messages/?session_id={fake_session_id}",
                    headers={"Content-Type": content_type},
                    json={"test": "data"},
                )
                # Will get 404 because session doesn't exist, but that's OK
                # We're testing that it passes the content-type check
                assert response.status_code == 404
                assert response.text == "Could not find session"

    finally:
        process.terminate()
        process.join()
