"""Tests for WebSocket server request validation."""

# pyright: reportDeprecated=false

import logging
import multiprocessing
import socket
import warnings

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.types import Message, Scope
from starlette.websockets import WebSocket
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus
from websockets.typing import Subprotocol

from mcp.server import Server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.server.websocket import websocket_server
from tests.test_helpers import wait_for_server

logger = logging.getLogger(__name__)
SERVER_NAME = "test_ws_security_server"

# This suite intentionally exercises the deprecated WebSocket transport.
pytestmark = pytest.mark.filterwarnings(
    "ignore:The WebSocket (client|server) transport is deprecated:DeprecationWarning"
)


@pytest.fixture
def server_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_server_with_settings(port: int, security_settings: TransportSecuritySettings | None = None):  # pragma: no cover
    """Run a WebSocket MCP server with the given security settings."""
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    server = Server(SERVER_NAME)

    async def handle_ws(websocket: WebSocket) -> None:
        try:
            async with websocket_server(
                websocket.scope, websocket.receive, websocket.send, security_settings=security_settings
            ) as streams:
                await server.run(streams[0], streams[1], server.create_initialization_options())
        except ValueError as exc:
            logger.debug(f"WebSocket connection failed validation: {exc}")

    app = Starlette(routes=[WebSocketRoute("/ws", endpoint=handle_ws)])
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")


def start_server_process(port: int, security_settings: TransportSecuritySettings | None = None):
    """Start the server in a subprocess and wait until it accepts connections."""
    process = multiprocessing.Process(target=run_server_with_settings, args=(port, security_settings))
    process.start()
    wait_for_server(port)
    return process


@pytest.mark.anyio
async def test_ws_security_default_settings(server_port: int) -> None:
    """With no security settings the WebSocket transport accepts any Origin (matches SSE/StreamableHTTP default)."""
    process = start_server_process(server_port)
    try:
        async with connect(
            f"ws://127.0.0.1:{server_port}/ws",
            subprotocols=[Subprotocol("mcp")],
            additional_headers={"Origin": "http://evil.com"},
        ) as ws:
            assert ws.subprotocol == "mcp"
    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_ws_security_invalid_origin_header(server_port: int) -> None:
    """An Origin not in allowed_origins is rejected before the handshake completes."""
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"], allowed_origins=["http://localhost:*"]
    )
    process = start_server_process(server_port, settings)
    try:
        with pytest.raises(InvalidStatus) as exc_info:
            async with connect(
                f"ws://127.0.0.1:{server_port}/ws",
                subprotocols=[Subprotocol("mcp")],
                additional_headers={"Origin": "http://evil.com"},
            ):
                pytest.fail("handshake should have been rejected")  # pragma: no cover
        assert exc_info.value.response.status_code == 403
    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_ws_security_invalid_host_header(server_port: int) -> None:
    """A Host not in allowed_hosts is rejected before the handshake completes."""
    settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["example.com"])
    process = start_server_process(server_port, settings)
    try:
        with pytest.raises(InvalidStatus) as exc_info:
            async with connect(f"ws://127.0.0.1:{server_port}/ws", subprotocols=[Subprotocol("mcp")]):
                pytest.fail("handshake should have been rejected")  # pragma: no cover
        assert exc_info.value.response.status_code == 403
    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_ws_security_allowed_origin(server_port: int) -> None:
    """An Origin matching allowed_origins is accepted."""
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"], allowed_origins=["http://localhost:*"]
    )
    process = start_server_process(server_port, settings)
    try:
        async with connect(
            f"ws://127.0.0.1:{server_port}/ws",
            subprotocols=[Subprotocol("mcp")],
            additional_headers={"Origin": "http://localhost:8080"},
        ) as ws:
            assert ws.subprotocol == "mcp"
    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_ws_security_disabled(server_port: int) -> None:
    """Explicitly disabling protection accepts any Origin."""
    settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    process = start_server_process(server_port, settings)
    try:
        async with connect(
            f"ws://127.0.0.1:{server_port}/ws",
            subprotocols=[Subprotocol("mcp")],
            additional_headers={"Origin": "http://evil.com"},
        ) as ws:
            assert ws.subprotocol == "mcp"
    finally:
        process.terminate()
        process.join()


@pytest.mark.anyio
async def test_ws_security_rejects_before_accept() -> None:
    """A failing validation closes the connection before the handshake is accepted."""
    settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["example.com"])
    sent: list[Message] = []

    async def receive() -> Message:
        raise NotImplementedError

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {"type": "websocket", "headers": [(b"host", b"evil.com")]}
    with pytest.raises(ValueError, match="Request validation failed"):
        async with websocket_server(scope, receive, send, security_settings=settings):
            pytest.fail("should not yield streams")  # pragma: no cover

    assert [m["type"] for m in sent] == ["websocket.close"]
