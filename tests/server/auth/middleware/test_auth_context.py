"""
Tests for the AuthContext middleware components.
"""

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
class TestAuthContextMiddleware:
    """Tests for the AuthContextMiddleware class."""

    async def test_with_authenticated_user(self, valid_access_token: AccessToken):
        """Test middleware with an authenticated user in scope."""
        app = MockApp()
        middleware = AuthContextMiddleware(app)

        # Create an authenticated user
        user = AuthenticatedUser(valid_access_token)

        scope: Scope = {"type": "http", "user": user}

        # Create dummy async functions for receive and send
        async def receive() -> Message:
            return {"type": "http.request"}

        async def send(message: Message) -> None:
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

    async def test_with_no_user(self):
        """Test middleware with no user in scope."""
        app = MockApp()
        middleware = AuthContextMiddleware(app)

        scope: Scope = {"type": "http"}  # No user

        # Create dummy async functions for receive and send
        async def receive() -> Message:
            return {"type": "http.request"}

        async def send(message: Message) -> None:
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
