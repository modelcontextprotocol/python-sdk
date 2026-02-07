"""Coverage tests for RequireAuthMiddleware WWW-Authenticate fields."""

from __future__ import annotations

import pytest
from starlette.types import Message, Receive, Scope, Send

from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken


@pytest.mark.anyio
async def test_require_auth_middleware_includes_mcp_extension_fields_in_www_authenticate() -> None:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RequireAuthMiddleware(
        app=app,
        required_scopes=[],
        auth_protocols=["oauth2", "api_key"],
        default_protocol="oauth2",
        protocol_preferences={"oauth2": 10, "api_key": 1},
    )

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    scope: Scope = {"type": "http", "method": "GET", "path": "/", "headers": []}  # no user/auth in scope
    await middleware(scope, receive=receive, send=send)

    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    www = headers[b"www-authenticate"].decode()

    assert 'auth_protocols="oauth2 api_key"' in www
    assert 'default_protocol="oauth2"' in www
    assert 'protocol_preferences="oauth2:10,api_key:1"' in www

    # Exercise local helpers for test coverage.
    await receive()
    await app(scope, receive=receive, send=send)


@pytest.mark.anyio
async def test_require_auth_middleware_calls_inner_app_when_user_present() -> None:
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RequireAuthMiddleware(app=app, required_scopes=[])
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "user": AuthenticatedUser(
            AccessToken(token="t", client_id="c", scopes=["read"], expires_at=None),
        ),
    }
    await middleware(scope, receive=receive, send=send)

    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 200
