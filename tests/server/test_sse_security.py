"""Tests for SSE server request validation."""

import logging
import re
from collections.abc import Generator
from contextlib import contextmanager

import anyio
import httpx
import pytest
import sse_starlette.sse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route
from starlette.types import Message, Receive, Scope, Send

from mcp.server import Server
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.sse import SseServerTransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared._stream_protocols import WriteStream
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCRequest, JSONRPCResponse, Tool
from tests.test_helpers import run_uvicorn_in_thread

logger = logging.getLogger(__name__)
SERVER_NAME = "test_sse_security_server"


@pytest.fixture(autouse=True)
def reset_sse_starlette_exit_event() -> None:
    """sse-starlette<2 caches a module-level anyio.Event on AppStatus; reset it
    between tests so it is not bound to a previous test's event loop."""
    app_status = getattr(sse_starlette.sse, "AppStatus", None)
    if app_status is not None and hasattr(app_status, "should_exit_event"):  # pragma: lax no cover
        app_status.should_exit_event = None


class SecurityTestServer(Server):  # pragma: no cover
    def __init__(self):
        super().__init__(SERVER_NAME)

    async def on_list_tools(self) -> list[Tool]:
        return []


def make_server_app(security_settings: TransportSecuritySettings | None = None) -> Starlette:  # pragma: no cover
    """Create the SSE server with specified security settings."""
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

    return Starlette(routes=routes)


@contextmanager
def run_server_with_settings(
    security_settings: TransportSecuritySettings | None = None,
) -> Generator[str, None, None]:
    """Run the SSE server without preselecting a port."""
    with run_uvicorn_in_thread(make_server_app(security_settings)) as url:
        yield url


@pytest.mark.anyio
async def test_sse_security_default_settings():
    """Test SSE with default security settings (protection disabled)."""
    with run_server_with_settings() as server_url:
        headers = {"Host": "evil.com", "Origin": "http://evil.com"}

        async with httpx.AsyncClient(timeout=5.0) as client:
            async with client.stream("GET", f"{server_url}/sse", headers=headers) as response:
                assert response.status_code == 200


@pytest.mark.anyio
async def test_sse_security_invalid_host_header():
    """Test SSE with invalid Host header."""
    # Enable security by providing settings with an empty allowed_hosts list
    security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["example.com"])
    with run_server_with_settings(security_settings) as server_url:
        # Test with invalid host header
        headers = {"Host": "evil.com"}

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{server_url}/sse", headers=headers)
            assert response.status_code == 421
            assert response.text == "Invalid Host header"


@pytest.mark.anyio
async def test_sse_security_invalid_origin_header():
    """Test SSE with invalid Origin header."""
    # Configure security to allow the host but restrict origins
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"], allowed_origins=["http://localhost:*"]
    )
    with run_server_with_settings(security_settings) as server_url:
        # Test with invalid origin header
        headers = {"Origin": "http://evil.com"}

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{server_url}/sse", headers=headers)
            assert response.status_code == 403
            assert response.text == "Invalid Origin header"


@pytest.mark.anyio
async def test_sse_security_post_invalid_content_type():
    """Test POST endpoint with invalid Content-Type header."""
    # Configure security to allow the host
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"], allowed_origins=["http://127.0.0.1:*"]
    )
    with run_server_with_settings(security_settings) as server_url:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Test POST with invalid content type
            fake_session_id = "12345678123456781234567812345678"
            response = await client.post(
                f"{server_url}/messages/?session_id={fake_session_id}",
                headers={"Content-Type": "text/plain"},
                content="test",
            )
            assert response.status_code == 400
            assert response.text == "Invalid Content-Type header"

            # Test POST with missing content type
            response = await client.post(
                f"{server_url}/messages/?session_id={fake_session_id}", content="test"
            )
            assert response.status_code == 400
            assert response.text == "Invalid Content-Type header"


@pytest.mark.anyio
async def test_sse_security_disabled():
    """Test SSE with security disabled."""
    settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    with run_server_with_settings(settings) as server_url:
        # Test with invalid host header - should still work
        headers = {"Host": "evil.com"}

        async with httpx.AsyncClient(timeout=5.0) as client:
            # For SSE endpoints, we need to use stream to avoid timeout
            async with client.stream("GET", f"{server_url}/sse", headers=headers) as response:
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
    with run_server_with_settings(settings) as server_url:
        # Test with custom allowed host
        headers = {"Host": "custom.host"}

        async with httpx.AsyncClient(timeout=5.0) as client:
            # For SSE endpoints, we need to use stream to avoid timeout
            async with client.stream("GET", f"{server_url}/sse", headers=headers) as response:
                # Should connect successfully with custom host
                assert response.status_code == 200

        # Test with non-allowed host
        headers = {"Host": "evil.com"}

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{server_url}/sse", headers=headers)
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
    with run_server_with_settings(settings) as server_url:
        # Test with various port numbers
        for test_port in [8080, 3000, 9999]:
            headers = {"Host": f"localhost:{test_port}"}

            async with httpx.AsyncClient(timeout=5.0) as client:
                # For SSE endpoints, we need to use stream to avoid timeout
                async with client.stream("GET", f"{server_url}/sse", headers=headers) as response:
                    # Should connect successfully with any port
                    assert response.status_code == 200

            headers = {"Origin": f"http://localhost:{test_port}"}

            async with httpx.AsyncClient(timeout=5.0) as client:
                # For SSE endpoints, we need to use stream to avoid timeout
                async with client.stream("GET", f"{server_url}/sse", headers=headers) as response:
                    # Should connect successfully with any port
                    assert response.status_code == 200


@pytest.mark.anyio
async def test_sse_security_post_valid_content_type():
    """Test POST endpoint with valid Content-Type headers."""
    # Configure security to allow the host
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"], allowed_origins=["http://127.0.0.1:*"]
    )
    with run_server_with_settings(security_settings) as server_url:
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
                    f"{server_url}/messages/?session_id={fake_session_id}",
                    headers={"Content-Type": content_type},
                    json={"test": "data"},
                )
                # Will get 404 because session doesn't exist, but that's OK
                # We're testing that it passes the content-type check
                assert response.status_code == 404
                assert response.text == "Could not find session"


def _authenticated_user(client_id: str, subject: str | None = None, issuer: str | None = None) -> AuthenticatedUser:
    """Build the scope["user"] value that AuthenticationMiddleware would set for this principal."""
    claims = {"iss": issuer} if issuer is not None else None
    return AuthenticatedUser(AccessToken(token="token", client_id=client_id, scopes=[], subject=subject, claims=claims))


def _sse_scope(
    method: str, path: str, user: AuthenticatedUser | None, *, query_string: bytes = b"", body: bytes = b""
) -> tuple[Scope, Receive, Send, list[Message]]:
    """Build an ASGI scope/receive/send triple for a request to the SSE transport."""
    scope: Scope = {
        "type": "http",
        "method": method,
        "path": path,
        "root_path": "",
        "query_string": query_string,
        "headers": [(b"content-type", b"application/json")],
    }
    if user is not None:
        scope["user"] = user
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    return scope, receive, send, sent


def _response_status(sent: list[Message]) -> int:
    response_start = next(msg for msg in sent if msg["type"] == "http.response.start")
    return response_start["status"]


async def _post_message(transport: SseServerTransport, session_id: str, user: AuthenticatedUser | None) -> int:
    """POST a message to an SSE session as `user` and return the response status."""
    body = b'{"jsonrpc": "2.0", "id": 1, "method": "ping", "params": null}'
    scope, receive, send, sent = _sse_scope(
        "POST", "/messages/", user, query_string=f"session_id={session_id}".encode(), body=body
    )
    await transport.handle_post_message(scope, receive, send)
    return _response_status(sent)


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
        scope, _, _, _ = _sse_scope("GET", "/sse", creator_user)
        with anyio.fail_after(5):
            async with transport.connect_sse(scope, get_receive, get_send) as (read_stream, write_stream):
                async with read_stream, write_stream:  # pragma: no branch
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


@pytest.mark.anyio
async def test_sse_connect_rejects_a_non_http_scope():
    """connect_sse refuses ASGI scopes that are not HTTP requests."""
    transport = SseServerTransport("/messages/")
    with pytest.raises(ValueError):
        async with transport.connect_sse({"type": "websocket"}, _no_receive, _no_send):
            raise NotImplementedError


@pytest.mark.anyio
async def test_sse_connect_rejects_a_disallowed_host():
    """connect_sse rejects requests whose Host header fails the configured security check."""
    settings = TransportSecuritySettings(allowed_hosts=["allowed.example.com"])
    transport = SseServerTransport("/messages/", security_settings=settings)
    scope, receive, send, sent = _sse_scope("GET", "/sse", None)
    scope["headers"] = [(b"host", b"disallowed.example.com")]

    with pytest.raises(ValueError):
        async with transport.connect_sse(scope, receive, send):
            raise NotImplementedError
    assert _response_status(sent) == 421


@pytest.mark.anyio
async def test_sse_post_without_a_session_id_returns_400():
    """POSTs to the messages endpoint must include a session_id query parameter."""
    transport = SseServerTransport("/messages/")
    scope, receive, send, sent = _sse_scope("POST", "/messages/", None)

    await transport.handle_post_message(scope, receive, send)
    assert _response_status(sent) == 400


@pytest.mark.anyio
async def test_sse_post_with_a_malformed_session_id_returns_400():
    """A session_id that is not 32 hex characters is rejected before any session lookup."""
    transport = SseServerTransport("/messages/")
    scope, receive, send, sent = _sse_scope("POST", "/messages/", None, query_string=b"session_id=not-hex")

    await transport.handle_post_message(scope, receive, send)
    assert _response_status(sent) == 400


@pytest.mark.anyio
async def test_sse_post_with_a_disallowed_host_is_rejected_before_session_lookup():
    """The transport security check on POST runs before any session-ID handling."""
    settings = TransportSecuritySettings(allowed_hosts=["allowed.example.com"])
    transport = SseServerTransport("/messages/", security_settings=settings)
    scope, receive, send, sent = _sse_scope("POST", "/messages/", None)
    scope["headers"] = [(b"host", b"disallowed.example.com"), (b"content-type", b"application/json")]

    await transport.handle_post_message(scope, receive, send)
    assert _response_status(sent) == 421


@pytest.mark.anyio
async def test_sse_round_trip_delivers_posted_messages_and_streams_responses():
    """A POSTed JSON-RPC message reaches the server's read stream, and a message
    written to the server's write stream is sent to the client as an SSE event."""
    transport = SseServerTransport("/messages/")
    session = _SseSession(transport)

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(session.hold)
            await session.ready.wait()

            # POST a parse-failing body: client gets 400, server's read stream receives the error.
            scope, receive, send, sent = _sse_scope(
                "POST", "/messages/", None, query_string=f"session_id={session.session_id}".encode(), body=b"not json"
            )
            await transport.handle_post_message(scope, receive, send)
            assert _response_status(sent) == 400
            assert isinstance(await session.next_read_item(), Exception)

            # POST a valid message: client gets 202, server's read stream receives it.
            assert await _post_message(transport, session.session_id, None) == 202
            received = await session.next_read_item()
            assert isinstance(received, SessionMessage)
            assert isinstance(received.message, JSONRPCRequest)
            assert received.message.method == "ping"

            # Server writes a response: it appears as an SSE `message` event on the GET stream.
            outgoing = JSONRPCResponse(jsonrpc="2.0", id=1, result={})
            await session.write_stream.send(SessionMessage(outgoing))
            chunk = await session.next_body_chunk()
            assert b"event: message" in chunk
            assert outgoing.model_dump_json(by_alias=True, exclude_unset=True).encode() in chunk

            session.disconnect()


class _SseSession:
    """Drive an in-process SSE GET connection and surface what the server reads and the client receives.

    `hold` runs the connection in a background task and consumes the server-side read stream
    into a buffer so that `handle_post_message` (which writes to that stream with a zero-capacity
    channel) never blocks the test body.
    """

    def __init__(self, transport: SseServerTransport) -> None:
        self.transport = transport
        self.ready = anyio.Event()
        self._disconnected = anyio.Event()
        self._body_send, self._body_recv = anyio.create_memory_object_stream[bytes](16)
        self._read_send, self._read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](16)
        self.session_id = ""
        self.write_stream: WriteStream[SessionMessage]

    async def hold(self) -> None:
        scope, _, _, _ = _sse_scope("GET", "/sse", None)
        async with self.transport.connect_sse(scope, self._receive, self._send) as (read, write):
            self.write_stream = write
            async with read, write, self._body_send, self._body_recv, self._read_send, self._read_recv:
                async for item in read:
                    await self._read_send.send(item)

    def disconnect(self) -> None:
        self._disconnected.set()

    async def next_read_item(self) -> SessionMessage | Exception:
        return await self._read_recv.receive()

    async def next_body_chunk(self) -> bytes:
        return await self._body_recv.receive()

    async def _receive(self) -> Message:
        await self._disconnected.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: Message) -> None:
        if message["type"] != "http.response.body":
            return
        body: bytes = message.get("body", b"")
        if not self.session_id:
            match = re.search(rb"session_id=([0-9a-f]{32})", body)
            assert match is not None, f"expected the endpoint event first, got {message!r}"
            self.session_id = match.group(1).decode()
            self.ready.set()
        else:
            await self._body_send.send(body)


async def _no_receive() -> Message:
    raise NotImplementedError


async def _no_send(message: Message) -> None:
    raise NotImplementedError
