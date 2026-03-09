"""Tests for SSE server DNS rebinding protection."""

import contextlib
import logging
from collections.abc import Generator

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool
from tests.test_helpers import run_uvicorn_in_thread

# Several tests open an SSE stream, check the status code, then exit without
# consuming the stream. When uvicorn shuts down, it cancels the still-running
# SSE handler mid-operation, and SseServerTransport's internal memory streams
# may be GC'd without their cleanup finalizers running. These ResourceWarnings
# are artifacts of the abrupt-disconnect test pattern, not production bugs.
pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")

logger = logging.getLogger(__name__)
SERVER_NAME = "test_sse_security_server"


class SecurityTestServer(Server):
    def __init__(self):
        super().__init__(SERVER_NAME)

    async def on_list_tools(self) -> list[Tool]:
        return []  # pragma: no cover


def make_app(security_settings: TransportSecuritySettings | None = None) -> Starlette:
    """Build a Starlette app with SSE transport and the given security settings."""
    app = SecurityTestServer()
    sse_transport = SseServerTransport("/messages/", security_settings)

    async def handle_sse(request: Request) -> Response:
        # connect_sse sends responses directly via ASGI `send` (both the SSE stream
        # and any validation error responses), so by the time we return here the
        # response has already been sent. Starlette will still try to send our
        # return value, which fails with "Unexpected ASGI message". We suppress
        # ValueError from connect_sse and wrap the final Response() send in a
        # no-op so Starlette's machinery doesn't conflict.
        with contextlib.suppress(ValueError):
            async with sse_transport.connect_sse(request.scope, request.receive, request._send) as streams:
                if streams:  # pragma: no branch
                    await app.run(streams[0], streams[1], app.create_initialization_options())
        return _AlreadySentResponse()

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse_transport.handle_post_message),
        ]
    )


class _AlreadySentResponse(Response):
    """No-op Response for handlers that already sent via raw ASGI `send`."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        pass


@pytest.fixture
def server_url() -> Generator[str, None, None]:
    """Default-settings server for tests that don't need custom security config."""
    with run_uvicorn_in_thread(make_app(), lifespan="off") as url:
        yield url


@pytest.mark.anyio
async def test_sse_security_default_settings(server_url: str):
    """Test SSE with default security settings (protection disabled)."""
    headers = {"Host": "evil.com", "Origin": "http://evil.com"}
    async with httpx.AsyncClient(timeout=5.0) as client:
        async with client.stream("GET", f"{server_url}/sse", headers=headers) as response:
            assert response.status_code == 200


@pytest.mark.anyio
async def test_sse_security_invalid_host_header():
    """Test SSE with invalid Host header."""
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["example.com"])
    with run_uvicorn_in_thread(make_app(security_settings), lifespan="off") as url:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{url}/sse", headers={"Host": "evil.com"})
            assert response.status_code == 421
            assert response.text == "Invalid Host header"


@pytest.mark.anyio
async def test_sse_security_invalid_origin_header():
    """Test SSE with invalid Origin header."""
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"], allowed_origins=["http://localhost:*"]
    )
    with run_uvicorn_in_thread(make_app(security_settings), lifespan="off") as url:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{url}/sse", headers={"Origin": "http://evil.com"})
            assert response.status_code == 403
            assert response.text == "Invalid Origin header"


@pytest.mark.anyio
async def test_sse_security_post_invalid_content_type():
    """Test POST endpoint with invalid Content-Type header."""
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"], allowed_origins=["http://127.0.0.1:*"]
    )
    with run_uvicorn_in_thread(make_app(security_settings), lifespan="off") as url:
        async with httpx.AsyncClient(timeout=5.0) as client:
            fake_session_id = "12345678123456781234567812345678"
            # Test POST with invalid content type
            response = await client.post(
                f"{url}/messages/?session_id={fake_session_id}",
                headers={"Content-Type": "text/plain"},
                content="test",
            )
            assert response.status_code == 400
            assert response.text == "Invalid Content-Type header"

            # Test POST with missing content type
            response = await client.post(f"{url}/messages/?session_id={fake_session_id}", content="test")
            assert response.status_code == 400
            assert response.text == "Invalid Content-Type header"


@pytest.mark.anyio
async def test_sse_security_disabled():
    """Test SSE with security disabled."""
    settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    with run_uvicorn_in_thread(make_app(settings), lifespan="off") as url:
        async with httpx.AsyncClient(timeout=5.0) as client:
            async with client.stream("GET", f"{url}/sse", headers={"Host": "evil.com"}) as response:
                # Should connect successfully even with invalid host
                assert response.status_code == 200


@pytest.mark.anyio
async def test_sse_security_custom_allowed_hosts():
    """Test SSE with custom allowed hosts."""
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost", "127.0.0.1", "custom.host"],
        allowed_origins=["http://localhost", "http://127.0.0.1", "http://custom.host"],
    )
    with run_uvicorn_in_thread(make_app(settings), lifespan="off") as url:
        # Test with custom allowed host
        async with httpx.AsyncClient(timeout=5.0) as client:
            async with client.stream("GET", f"{url}/sse", headers={"Host": "custom.host"}) as response:
                assert response.status_code == 200

        # Test with non-allowed host
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{url}/sse", headers={"Host": "evil.com"})
            assert response.status_code == 421
            assert response.text == "Invalid Host header"


@pytest.mark.anyio
async def test_sse_security_wildcard_ports():
    """Test SSE with wildcard port patterns."""
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost:*", "127.0.0.1:*"],
        allowed_origins=["http://localhost:*", "http://127.0.0.1:*"],
    )
    with run_uvicorn_in_thread(make_app(settings), lifespan="off") as url:
        # Test with various port numbers
        for test_port in [8080, 3000, 9999]:
            async with httpx.AsyncClient(timeout=5.0) as client:
                async with client.stream("GET", f"{url}/sse", headers={"Host": f"localhost:{test_port}"}) as response:
                    assert response.status_code == 200

            async with httpx.AsyncClient(timeout=5.0) as client:
                headers = {"Origin": f"http://localhost:{test_port}"}
                async with client.stream("GET", f"{url}/sse", headers=headers) as response:
                    assert response.status_code == 200


@pytest.mark.anyio
async def test_sse_security_post_valid_content_type():
    """Test POST endpoint with valid Content-Type headers."""
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"], allowed_origins=["http://127.0.0.1:*"]
    )
    with run_uvicorn_in_thread(make_app(security_settings), lifespan="off") as url:
        async with httpx.AsyncClient() as client:
            valid_content_types = [
                "application/json",
                "application/json; charset=utf-8",
                "application/json;charset=utf-8",
                "APPLICATION/JSON",  # Case insensitive
            ]
            for content_type in valid_content_types:
                fake_session_id = "12345678123456781234567812345678"
                response = await client.post(
                    f"{url}/messages/?session_id={fake_session_id}",
                    headers={"Content-Type": content_type},
                    json={"test": "data"},
                )
                # Will get 404 because session doesn't exist — that means we passed content-type validation
                assert response.status_code == 404
                assert response.text == "Could not find session"
