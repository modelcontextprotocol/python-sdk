import time

import pytest
from starlette.types import Message, Receive, Scope, Send

from mcp.server.auth.middleware.auth_context import (
    AuthContextMiddleware,
    auth_context_var,
    get_access_token,
)
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken


class MockApp:
    def __init__(self):
        self.called = False
        self.scope: Scope | None = None
        self.receive: Receive | None = None
        self.send: Send | None = None
        self.access_token_during_call: AccessToken | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.called = True
        self.scope = scope
        self.receive = receive
        self.send = send
        self.access_token_during_call = get_access_token()


@pytest.fixture
def valid_access_token() -> AccessToken:
    return AccessToken(
        token="valid_token",
        client_id="test_client",
        scopes=["read", "write"],
        expires_at=int(time.time()) + 3600,
    )


@pytest.mark.anyio
async def test_auth_context_middleware_with_authenticated_user(valid_access_token: AccessToken):
    app = MockApp()
    middleware = AuthContextMiddleware(app)

    user = AuthenticatedUser(valid_access_token)

    scope: Scope = {"type": "http", "user": user}

    async def receive() -> Message:  # pragma: no cover
        return {"type": "http.request"}

    async def send(message: Message) -> None:  # pragma: no cover
        pass

    assert auth_context_var.get() is None
    assert get_access_token() is None

    await middleware(scope, receive, send)

    assert app.called
    assert app.scope == scope
    assert app.receive == receive
    assert app.send == send

    assert app.access_token_during_call == valid_access_token

    # contextvar must be reset once the request completes
    assert auth_context_var.get() is None
    assert get_access_token() is None


@pytest.mark.anyio
async def test_auth_context_middleware_with_no_user():
    app = MockApp()
    middleware = AuthContextMiddleware(app)

    scope: Scope = {"type": "http"}

    async def receive() -> Message:  # pragma: no cover
        return {"type": "http.request"}

    async def send(message: Message) -> None:  # pragma: no cover
        pass

    assert auth_context_var.get() is None
    assert get_access_token() is None

    await middleware(scope, receive, send)

    assert app.called
    assert app.scope == scope
    assert app.receive == receive
    assert app.send == send

    assert app.access_token_during_call is None

    assert auth_context_var.get() is None
    assert get_access_token() is None
