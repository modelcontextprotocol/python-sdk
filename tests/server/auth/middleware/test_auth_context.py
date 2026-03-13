"""Tests for the AuthContext middleware components."""

import time

import pytest
from starlette.types import Message, Receive, Scope, Send

from mcp.server.auth.middleware.auth_context import (
    AuthContextMiddleware,
    auth_context_var,
    get_access_token,
    get_tenant_id,
)
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.shared._context import tenant_id_var


class MockApp:
    """Mock ASGI app for testing."""

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
        # Check the context during the call
        self.access_token_during_call = get_access_token()


@pytest.fixture
def valid_access_token() -> AccessToken:
    """Create a valid access token."""
    return AccessToken(
        token="valid_token",
        client_id="test_client",
        scopes=["read", "write"],
        expires_at=int(time.time()) + 3600,  # 1 hour from now
    )


@pytest.mark.anyio
async def test_auth_context_middleware_with_authenticated_user(valid_access_token: AccessToken):
    """Test middleware with an authenticated user in scope."""
    app = MockApp()
    middleware = AuthContextMiddleware(app)

    # Create an authenticated user
    user = AuthenticatedUser(valid_access_token)

    scope: Scope = {"type": "http", "user": user}

    # Create dummy async functions for receive and send
    async def receive() -> Message:  # pragma: no cover
        return {"type": "http.request"}

    async def send(message: Message) -> None:  # pragma: no cover
        pass

    # Verify context is empty before middleware
    assert auth_context_var.get() is None
    assert get_access_token() is None

    # Run the middleware
    await middleware(scope, receive, send)

    # Verify the app was called
    assert app.called
    assert app.scope == scope
    assert app.receive == receive
    assert app.send == send

    # Verify the access token was available during the call
    assert app.access_token_during_call == valid_access_token

    # Verify context is reset after middleware
    assert auth_context_var.get() is None
    assert get_access_token() is None


@pytest.mark.anyio
async def test_auth_context_middleware_with_no_user():
    """Test middleware with no user in scope."""
    app = MockApp()
    middleware = AuthContextMiddleware(app)

    scope: Scope = {"type": "http"}  # No user

    # Create dummy async functions for receive and send
    async def receive() -> Message:  # pragma: no cover
        return {"type": "http.request"}

    async def send(message: Message) -> None:  # pragma: no cover
        pass

    # Verify context is empty before middleware
    assert auth_context_var.get() is None
    assert get_access_token() is None

    # Run the middleware
    await middleware(scope, receive, send)

    # Verify the app was called
    assert app.called
    assert app.scope == scope
    assert app.receive == receive
    assert app.send == send

    # Verify the access token was not available during the call
    assert app.access_token_during_call is None

    # Verify context is still empty after middleware
    assert auth_context_var.get() is None
    assert get_access_token() is None


@pytest.fixture
def access_token_with_tenant() -> AccessToken:
    """Create an access token with a tenant_id."""
    return AccessToken(
        token="tenant_token",
        client_id="test_client",
        scopes=["read", "write"],
        expires_at=int(time.time()) + 3600,
        tenant_id="tenant-abc",
    )


def test_get_tenant_id_without_auth_context():
    """Test get_tenant_id returns None when no auth context exists."""
    assert auth_context_var.get() is None
    assert get_tenant_id() is None


@pytest.mark.anyio
async def test_get_tenant_id_with_tenant(access_token_with_tenant: AccessToken):
    """Test get_tenant_id returns tenant_id when auth context has a tenant."""
    app = MockApp()
    middleware = AuthContextMiddleware(app)

    user = AuthenticatedUser(access_token_with_tenant)
    scope: Scope = {"type": "http", "user": user}

    tenant_id_during_call: str | None = None

    class TenantCheckApp:
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal tenant_id_during_call
            tenant_id_during_call = get_tenant_id()

    middleware = AuthContextMiddleware(TenantCheckApp())

    async def receive() -> Message:  # pragma: no cover
        return {"type": "http.request"}

    async def send(message: Message) -> None:  # pragma: no cover
        pass

    await middleware(scope, receive, send)

    assert tenant_id_during_call == "tenant-abc"
    # Verify context is reset after middleware
    assert get_tenant_id() is None


@pytest.mark.anyio
async def test_middleware_sets_tenant_id_var(access_token_with_tenant: AccessToken):
    """Test AuthContextMiddleware populates the transport-agnostic tenant_id_var."""
    user = AuthenticatedUser(access_token_with_tenant)
    scope: Scope = {"type": "http", "user": user}

    observed_tenant_id: str | None = None

    class CheckApp:
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal observed_tenant_id
            observed_tenant_id = tenant_id_var.get()

    middleware = AuthContextMiddleware(CheckApp())

    async def receive() -> Message:  # pragma: no cover
        return {"type": "http.request"}

    async def send(message: Message) -> None:  # pragma: no cover
        pass

    await middleware(scope, receive, send)

    assert observed_tenant_id == "tenant-abc"
    # Verify contextvar is reset after middleware
    assert tenant_id_var.get() is None


@pytest.mark.anyio
async def test_middleware_sets_tenant_id_var_none_without_tenant(valid_access_token: AccessToken):
    """Test AuthContextMiddleware sets tenant_id_var to None when token has no tenant."""
    user = AuthenticatedUser(valid_access_token)
    scope: Scope = {"type": "http", "user": user}

    observed_tenant_id: str | None = "sentinel"

    class CheckApp:
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal observed_tenant_id
            observed_tenant_id = tenant_id_var.get()

    middleware = AuthContextMiddleware(CheckApp())

    async def receive() -> Message:  # pragma: no cover
        return {"type": "http.request"}

    async def send(message: Message) -> None:  # pragma: no cover
        pass

    await middleware(scope, receive, send)

    assert observed_tenant_id is None


@pytest.mark.anyio
async def test_get_tenant_id_without_tenant(valid_access_token: AccessToken):
    """Test get_tenant_id returns None when auth context has no tenant."""
    tenant_id_during_call: str | None = "not-none"

    class TenantCheckApp:
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal tenant_id_during_call
            tenant_id_during_call = get_tenant_id()

    middleware = AuthContextMiddleware(TenantCheckApp())

    user = AuthenticatedUser(valid_access_token)
    scope: Scope = {"type": "http", "user": user}

    async def receive() -> Message:  # pragma: no cover
        return {"type": "http.request"}

    async def send(message: Message) -> None:  # pragma: no cover
        pass

    await middleware(scope, receive, send)

    assert tenant_id_during_call is None
