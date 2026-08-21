"""Tests for the request checks shared by the HTTP server transports."""

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from starlette.types import Message, Receive, Scope, Send

from mcp.server.transport_security import RequestBodyLimitMiddleware


@pytest.mark.anyio
async def test_request_body_chunks_are_replayed_as_one_message() -> None:
    """SDK-defined: raw ASGI proves chunk overhead is discarded before the body reaches the transport."""
    request_messages: Iterator[Message] = iter(
        [
            {"type": "http.request", "body": b"12", "more_body": True},
            {"type": "http.request", "body": b"34", "more_body": True},
            {"type": "http.request", "body": b"56", "more_body": False},
            {"type": "http.disconnect"},
        ]
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
        {"type": "http.request", "body": b"123456", "more_body": False},
        {"type": "http.disconnect"},
    ]


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
async def test_disconnect_before_request_body_is_replayed() -> None:
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
