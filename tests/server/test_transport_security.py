"""Tests for the request checks shared by the HTTP server transports."""

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request
from starlette.types import Message, Receive, Scope, Send

from mcp.server.transport_security import (
    RequestBodyLimitMiddleware,
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)


def _request(host: str | None, origin: str | None, content_type: str | None = "application/json") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if content_type is not None:
        headers.append((b"content-type", content_type.encode()))
    if host is not None:
        headers.append((b"host", host.encode()))
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "method": "GET", "headers": headers})


SETTINGS = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["good.example", "wild.example:*"],
    allowed_origins=["http://good.example", "http://wild.example:*"],
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("host", "origin", "expected"),
    [
        pytest.param(None, None, 421, id="missing-host"),
        pytest.param("evil.example", None, 421, id="host-no-match"),
        pytest.param("evil.example:9000", None, 421, id="host-wildcard-base-mismatch"),
        pytest.param("good.example", None, None, id="host-exact-no-origin"),
        pytest.param("wild.example:9000", None, None, id="host-wildcard-match"),
        pytest.param("good.example", "http://evil.example", 403, id="origin-no-match"),
        pytest.param("good.example", "http://evil.example:9000", 403, id="origin-wildcard-base-mismatch"),
        pytest.param("good.example", "http://good.example", None, id="origin-exact"),
        pytest.param("good.example", "http://wild.example:9000", None, id="origin-wildcard-match"),
    ],
)
async def test_validate_request_checks_host_then_origin(
    host: str | None, origin: str | None, expected: int | None
) -> None:
    """Host is checked first, then Origin; exact and wildcard-port allowlist entries are honoured."""
    middleware = TransportSecurityMiddleware(SETTINGS)
    response = await middleware.validate_request(_request(host, origin))
    assert (None if response is None else response.status_code) == expected


@pytest.mark.anyio
async def test_validate_request_skips_host_and_origin_when_protection_is_disabled() -> None:
    """With DNS-rebinding protection off, any Host/Origin is accepted."""
    middleware = TransportSecurityMiddleware(TransportSecuritySettings(enable_dns_rebinding_protection=False))
    assert await middleware.validate_request(_request("evil.example", "http://evil.example")) is None


@pytest.mark.anyio
async def test_validate_request_defaults_to_protection_disabled() -> None:
    """Constructing the middleware without settings leaves DNS-rebinding protection off."""
    middleware = TransportSecurityMiddleware()
    assert await middleware.validate_request(_request("evil.example", "http://evil.example")) is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        pytest.param("application/json", None, id="json"),
        pytest.param("application/json; charset=utf-8", None, id="json-with-charset"),
        pytest.param("APPLICATION/JSON", None, id="case-insensitive"),
        pytest.param("text/plain", 400, id="wrong-type"),
        pytest.param(None, 400, id="missing"),
    ],
)
async def test_validate_request_checks_content_type_on_post(content_type: str | None, expected: int | None) -> None:
    """POST requests must carry an application/json Content-Type, regardless of DNS-rebinding settings."""
    middleware = TransportSecurityMiddleware()
    response = await middleware.validate_request(_request("any", None, content_type=content_type), is_post=True)
    assert (None if response is None else response.status_code) == expected


@pytest.mark.anyio
async def test_validate_request_ignores_content_type_on_get() -> None:
    """Content-Type is only enforced for POST requests."""
    middleware = TransportSecurityMiddleware(SETTINGS)
    response = await middleware.validate_request(_request("good.example", None, content_type="text/plain"))
    assert response is None


@pytest.mark.anyio
async def test_client_disconnect_while_streaming_request_body_is_replayed() -> None:
    """SDK-defined: raw ASGI is required to prove a disconnect before body completion reaches the transport."""
    disconnect: Message = {"type": "http.disconnect"}
    request_messages: Iterator[Message] = iter(
        [{"type": "http.request", "body": b"1234", "more_body": True}, disconnect]
    )
    received_messages: list[Message] = []

    async def receive() -> Message:
        return next(request_messages)

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        received_messages.append(await receive())
        received_messages.append(await receive())

    scope: Scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": []}
    middleware = RequestBodyLimitMiddleware(app, max_body_size=8)

    await middleware(scope, receive, AsyncMock())

    assert received_messages == [
        {"type": "http.request", "body": b"1234", "more_body": True},
        disconnect,
    ]


@pytest.mark.anyio
async def test_client_disconnect_before_request_body_is_replayed() -> None:
    """SDK-defined: raw ASGI proves a disconnect before the first body message reaches the transport."""
    disconnect: Message = {"type": "http.disconnect"}
    received_messages: list[Message] = []

    async def receive() -> Message:
        return disconnect

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        received_messages.append(await receive())

    scope: Scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": []}
    middleware = RequestBodyLimitMiddleware(app, max_body_size=8)

    await middleware(scope, receive, AsyncMock())

    assert received_messages == [disconnect]


@pytest.mark.anyio
async def test_request_body_chunks_are_replayed_as_one_message() -> None:
    """SDK-defined: raw ASGI proves chunk overhead is discarded before the body reaches the transport."""
    request_messages: Iterator[Message] = iter(
        [
            {"type": "http.request", "body": b"12", "more_body": True},
            {"type": "http.request", "body": b"34", "more_body": True},
            {"type": "http.request", "body": b"56", "more_body": False},
        ]
    )
    received_messages: list[Message] = []

    async def receive() -> Message:
        return next(request_messages)

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        received_messages.append(await receive())

    scope: Scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": []}
    middleware = RequestBodyLimitMiddleware(app, max_body_size=8)

    await middleware(scope, receive, AsyncMock())

    assert received_messages == [{"type": "http.request", "body": b"123456", "more_body": False}]


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["GET", "PUT", "OPTIONS", "HEAD", "DELETE"])
async def test_request_body_limit_applies_to_every_method(method: str) -> None:
    """SDK-defined: the limit is a property of the request body, not of the method that carries it."""
    app = AsyncMock()
    sent_messages: list[Message] = []
    receive = AsyncMock(return_value={"type": "http.request", "body": b"123456789", "more_body": False})

    async def send(message: Message) -> None:
        sent_messages.append(message)

    scope: Scope = {"type": "http", "method": method, "path": "/mcp", "headers": []}
    middleware = RequestBodyLimitMiddleware(app, max_body_size=8)

    await middleware(scope, receive, send)

    assert [message["status"] for message in sent_messages if message["type"] == "http.response.start"] == [413]
    app.assert_not_awaited()


@pytest.mark.anyio
async def test_request_body_limit_leaves_non_http_scopes_alone() -> None:
    """SDK-defined: only HTTP requests carry a body to limit; other ASGI scopes go straight to the app."""
    app = AsyncMock()
    receive = AsyncMock()
    send = AsyncMock()
    scope: Scope = {"type": "lifespan"}
    middleware = RequestBodyLimitMiddleware(app, max_body_size=8)

    await middleware(scope, receive, send)

    app.assert_awaited_once_with(scope, receive, send)
    receive.assert_not_awaited()
