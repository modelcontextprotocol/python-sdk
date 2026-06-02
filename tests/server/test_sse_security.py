"""Tests for SSE server request validation."""

import logging
import multiprocessing
import re
import socket
from collections.abc import Iterator
from typing import Any

import anyio
import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route
from starlette.types import Message

from mcp.server import Server
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.sse import SseServerTransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool
from tests.test_helpers import wait_for_server

logger = logging.getLogger(__name__)
SERVER_NAME = "test_sse_security_server"


@pytest.fixture(autouse=True)
def reset_sse_starlette_exit_event() -> Iterator[None]:
    """sse-starlette<2 caches a module-level anyio.Event on AppStatus; clear it
    around each test so it is never bound to a closed event loop. Clearing it
    afterwards matters too: later test modules fork uvicorn subprocesses on
    Linux and would otherwise inherit a stale event."""
    from sse_starlette.sse import AppStatus

    def clear() -> None:
        if hasattr(AppStatus, "should_exit_event"):  # pragma: no cover
            setattr(AppStatus, "should_exit_event", None)

    clear()
    yield
    clear()


@pytest.fixture
def server_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url(server_port: int) -> str:  # pragma: no cover
    return f"http://127.0.0.1:{server_port}"


class SecurityTestServer(Server):  # pragma: no cover
    def __init__(self):
        super().__init__(SERVER_NAME)

    async def on_list_tools(self) -> list[Tool]:
        return []


def run_server_with_settings(port: int, security_settings: TransportSecuritySettings | None = None):  # pragma: no cover
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
    # Wait for server to be ready to accept connections
    wait_for_server(port)
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


def _authenticated_user(client_id: str, subject: str | None = None, issuer: str | None = None) -> AuthenticatedUser:
    """Build the scope["user"] value that AuthenticationMiddleware would set for this principal."""
    claims = {"iss": issuer} if issuer is not None else None
    return AuthenticatedUser(AccessToken(token="token", client_id=client_id, scopes=[], subject=subject, claims=claims))


def _sse_scope(method: str, path: str, user: AuthenticatedUser | None) -> dict[str, Any]:
    """Build an ASGI scope for a request to the SSE transport."""
    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,
        "root_path": "",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
    }
    if user is not None:
        scope["user"] = user
    return scope


async def _post_message(transport: SseServerTransport, session_id: str, user: AuthenticatedUser | None) -> int:
    """POST a message to an SSE session as `user` and return the response status."""
    body = b'{"jsonrpc": "2.0", "id": 1, "method": "ping", "params": null}'
    scope = _sse_scope("POST", "/messages/", user)
    scope["query_string"] = f"session_id={session_id}".encode()
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    await transport.handle_post_message(scope, receive, send)
    response_start = next(msg for msg in sent if msg["type"] == "http.response.start")
    return response_start["status"]


_Principal = tuple[str] | tuple[str, str] | tuple[str, str, str]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("creator", "sender", "expected"),
    [
        pytest.param(("client-a",), ("client-b",), 404, id="different-client"),
        pytest.param(("client-a",), None, 404, id="unauthenticated-sender"),
        pytest.param(("client-a", "alice"), ("client-a", "bob"), 404, id="same-client-different-subject"),
        pytest.param(("client-a", "alice"), ("client-a",), 404, id="same-client-no-subject"),
        pytest.param(
            ("client-a", "alice", "https://i1"), ("client-a", "alice", "https://i2"), 404, id="different-issuer"
        ),
        pytest.param(None, ("client-a",), 404, id="unauthenticated-creator"),
        pytest.param(("client-a",), ("client-a",), 202, id="same-client"),
        pytest.param(("client-a", "alice"), ("client-a", "alice"), 202, id="same-client-and-subject"),
        pytest.param(None, None, 202, id="both-unauthenticated"),
    ],
)
async def test_sse_post_requires_the_credential_that_created_the_session(
    creator: _Principal | None,
    sender: _Principal | None,
    expected: int,
):
    """The session endpoint URL issued to one authenticated principal must not
    accept messages from a request authenticated as a different one."""
    transport = SseServerTransport("/messages/")
    session_id_received = anyio.Event()
    session_ids: list[str] = []
    client_disconnected = anyio.Event()

    async def get_send(message: Message) -> None:
        # The first body chunk is the SSE event announcing the session URI to POST messages to.
        if message["type"] == "http.response.body" and not session_ids:
            match = re.search(rb"session_id=([0-9a-f]{32})", message.get("body", b""))
            assert match is not None, f"expected the endpoint event first, got {message!r}"
            session_ids.append(match.group(1).decode())
            session_id_received.set()

    async def get_receive() -> Message:
        # The SSE client stays connected until the test signals otherwise.
        await client_disconnected.wait()
        return {"type": "http.disconnect"}

    creator_user = _authenticated_user(*creator) if creator is not None else None
    sender_user = _authenticated_user(*sender) if sender is not None else None

    async def hold_sse_connection() -> None:
        """Establish the SSE session as `creator` and keep it open, as a server would."""
        scope = _sse_scope("GET", "/sse", creator_user)
        with anyio.fail_after(5):
            async with transport.connect_sse(scope, get_receive, get_send) as (read_stream, write_stream):
                async with read_stream, write_stream:  # pragma: no branch
                    # ^ coverage.py misses the ->exit arc on 3.11+ when the body
                    # is nested inside multiple async with blocks
                    async for _ in read_stream:
                        pass

    async with anyio.create_task_group() as tg:
        tg.start_soon(hold_sse_connection)
        with anyio.fail_after(5):
            await session_id_received.wait()

        assert await _post_message(transport, session_ids[0], sender_user) == expected

        client_disconnected.set()

    # Once the connection is gone the session is no longer routable.
    assert await _post_message(transport, session_ids[0], creator_user) == 404
