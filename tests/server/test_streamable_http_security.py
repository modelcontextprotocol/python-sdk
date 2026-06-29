"""Tests for StreamableHTTP server DNS rebinding protection."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from tests.interaction.transports import StreamingASGITransport

SERVER_NAME = "test_streamable_http_security_server"

# Nothing listens here; the origin only makes URLs well-formed with a localhost-form default Host header.
BASE_URL = "http://127.0.0.1:8000"


@asynccontextmanager
async def streamable_http_security_client(
    security_settings: TransportSecuritySettings | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    session_manager = StreamableHTTPSessionManager(app=Server(SERVER_NAME), security_settings=security_settings)
    app = Starlette(routes=[Mount("/", app=session_manager.handle_request)])

    async with session_manager.run():
        async with httpx.AsyncClient(transport=StreamingASGITransport(app), base_url=BASE_URL) as client:
            yield client


def _base_headers() -> dict[str, str]:
    """Common headers, so each test varies only the header under test."""
    return {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _initialize_body() -> dict[str, object]:
    """Minimal initialize body; these tests assert header validation, not the handshake."""
    return {"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}}


@pytest.mark.anyio
async def test_streamable_http_security_default_settings() -> None:
    async with streamable_http_security_client() as client:
        response = await client.post("/", json=_initialize_body(), headers=_base_headers())
        assert response.status_code == 200
        assert "mcp-session-id" in response.headers


@pytest.mark.anyio
async def test_streamable_http_security_invalid_host_header() -> None:
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True)

    async with streamable_http_security_client(security_settings) as client:
        response = await client.post("/", json=_initialize_body(), headers=_base_headers() | {"Host": "evil.com"})
        assert response.status_code == 421
        assert response.text == "Invalid Host header"


@pytest.mark.anyio
async def test_streamable_http_security_invalid_origin_header() -> None:
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"])

    async with streamable_http_security_client(security_settings) as client:
        response = await client.post(
            "/", json=_initialize_body(), headers=_base_headers() | {"Origin": "http://evil.com"}
        )
        assert response.status_code == 403
        assert response.text == "Invalid Origin header"


@pytest.mark.anyio
async def test_streamable_http_security_invalid_content_type() -> None:
    async with streamable_http_security_client() as client:
        response = await client.post("/", headers=_base_headers() | {"Content-Type": "text/plain"}, content="test")
        assert response.status_code == 400
        assert response.text == "Invalid Content-Type header"

        response = await client.post("/", headers={"Accept": "application/json, text/event-stream"}, content="test")
        assert response.status_code == 400
        assert response.text == "Invalid Content-Type header"


@pytest.mark.anyio
async def test_streamable_http_security_disabled() -> None:
    settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)

    async with streamable_http_security_client(settings) as client:
        response = await client.post("/", json=_initialize_body(), headers=_base_headers() | {"Host": "evil.com"})
        assert response.status_code == 200


@pytest.mark.anyio
async def test_streamable_http_security_custom_allowed_hosts() -> None:
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost", "127.0.0.1", "custom.host"],
        allowed_origins=["http://localhost", "http://127.0.0.1", "http://custom.host"],
    )

    async with streamable_http_security_client(settings) as client:
        response = await client.post("/", json=_initialize_body(), headers=_base_headers() | {"Host": "custom.host"})
        assert response.status_code == 200


@pytest.mark.anyio
async def test_streamable_http_security_get_request() -> None:
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1"])

    async with streamable_http_security_client(security_settings) as client:
        response = await client.get("/", headers={"Accept": "text/event-stream", "Host": "evil.com"})
        assert response.status_code == 421
        assert response.text == "Invalid Host header"

        response = await client.get("/", headers={"Accept": "text/event-stream", "Host": "127.0.0.1"})
        # An allowed host passes security and fails on session validation instead.
        assert response.status_code == 400
        body = response.json()
        assert "Missing session ID" in body["error"]["message"]
