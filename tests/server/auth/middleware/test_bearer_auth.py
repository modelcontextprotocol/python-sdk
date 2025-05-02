"""
Tests for the BearerAuth middleware components.
"""

import time
from typing import Any, cast

import pytest
from starlette.authentication import AuthCredentials
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.types import Message, Receive, Scope, Send

from mcp.server.auth.middleware.bearer_auth import (
    AuthenticatedUser,
    BearerAuthBackend,
    RequireAuthMiddleware,
)
from mcp.server.auth.provider import (
    AccessToken,
    OAuthAuthorizationServerProvider,
)


class MockOAuthProvider:
    """Mock OAuth provider for testing.

    This is a simplified version that only implements the methods needed for testing
    the BearerAuthMiddleware components.
    """

    def __init__(self):
        self.tokens = {}  # token -> AccessToken

    def add_token(self, token: str, access_token: AccessToken) -> None:
        """Add a token to the provider."""
        self.tokens[token] = access_token

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Load an access token."""
        return self.tokens.get(token)


def add_token_to_provider(
    provider: OAuthAuthorizationServerProvider[Any, Any, Any],
    token: str,
    access_token: AccessToken,
) -> None:
    """Helper function to add a token to a provider.

    This is used to work around type checking issues with our mock provider.
    """
    # We know this is actually a MockOAuthProvider
    mock_provider = cast(MockOAuthProvider, provider)
    mock_provider.add_token(token, access_token)


class MockApp:
    """Mock ASGI app for testing."""

    def __init__(self):
        self.called = False
        self.scope: Scope | None = None
        self.receive: Receive | None = None
        self.send: Send | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.called = True
        self.scope = scope
        self.receive = receive
        self.send = send


@pytest.fixture
def mock_oauth_provider() -> OAuthAuthorizationServerProvider[Any, Any, Any]:
    """Create a mock OAuth provider."""
    # Use type casting to satisfy the type checker
    return cast(OAuthAuthorizationServerProvider[Any, Any, Any], MockOAuthProvider())


@pytest.fixture
def valid_access_token() -> AccessToken:
    """Create a valid access token."""
    return AccessToken(
        token="valid_token",
        client_id="test_client",
        scopes=["read", "write"],
        expires_at=int(time.time()) + 3600,  # 1 hour from now
    )


@pytest.fixture
def expired_access_token() -> AccessToken:
    """Create an expired access token."""
    return AccessToken(
        token="expired_token",
        client_id="test_client",
        scopes=["read"],
        expires_at=int(time.time()) - 3600,  # 1 hour ago
    )


@pytest.fixture
def no_expiry_access_token() -> AccessToken:
    """Create an access token with no expiry."""
    return AccessToken(
        token="no_expiry_token",
        client_id="test_client",
        scopes=["read", "write"],
        expires_at=None,
    )


@pytest.mark.anyio
class TestBearerAuthBackend:
    """Tests for the BearerAuthBackend class."""

    async def test_no_auth_header(
        self, mock_oauth_provider: OAuthAuthorizationServerProvider[Any, Any, Any]
    ):
        """Test authentication with no Authorization header."""
        backend = BearerAuthBackend(provider=mock_oauth_provider)
        request = Request({"type": "http", "headers": []})
        result = await backend.authenticate(request)
        assert result is None

    async def test_non_bearer_auth_header(
        self, mock_oauth_provider: OAuthAuthorizationServerProvider[Any, Any, Any]
    ):
        """Test authentication with non-Bearer Authorization header."""
        backend = BearerAuthBackend(provider=mock_oauth_provider)
        request = Request(
            {
                "type": "http",
                "headers": [(b"authorization", b"Basic dXNlcjpwYXNz")],
            }
        )
        result = await backend.authenticate(request)
        assert result is None

    async def test_invalid_token(
        self, mock_oauth_provider: OAuthAuthorizationServerProvider[Any, Any, Any]
    ):
        """Test authentication with invalid token."""
        backend = BearerAuthBackend(provider=mock_oauth_provider)
        request = Request(
            {
                "type": "http",
                "headers": [(b"authorization", b"Bearer invalid_token")],
            }
        )
        result = await backend.authenticate(request)
        assert result is None

    async def test_expired_token(
        self,
        mock_oauth_provider: OAuthAuthorizationServerProvider[Any, Any, Any],
        expired_access_token: AccessToken,
    ):
        """Test authentication with expired token."""
        backend = BearerAuthBackend(provider=mock_oauth_provider)
        add_token_to_provider(
            mock_oauth_provider, "expired_token", expired_access_token
        )
        request = Request(
            {
                "type": "http",
                "headers": [(b"authorization", b"Bearer expired_token")],
            }
        )
        result = await backend.authenticate(request)
        assert result is None

    async def test_valid_token(
        self,
        mock_oauth_provider: OAuthAuthorizationServerProvider[Any, Any, Any],
        valid_access_token: AccessToken,
    ):
        """Test authentication with valid token."""
        backend = BearerAuthBackend(provider=mock_oauth_provider)
        add_token_to_provider(mock_oauth_provider, "valid_token", valid_access_token)
        request = Request(
            {
                "type": "http",
                "headers": [(b"authorization", b"Bearer valid_token")],
            }
        )
        result = await backend.authenticate(request)
        assert result is not None
        credentials, user = result
        assert isinstance(credentials, AuthCredentials)
        assert isinstance(user, AuthenticatedUser)
        assert credentials.scopes == ["read", "write"]
        assert user.display_name == "test_client"
        assert user.access_token == valid_access_token
        assert user.scopes == ["read", "write"]

    async def test_token_without_expiry(
        self,
        mock_oauth_provider: OAuthAuthorizationServerProvider[Any, Any, Any],
        no_expiry_access_token: AccessToken,
    ):
        """Test authentication with token that has no expiry."""
        backend = BearerAuthBackend(provider=mock_oauth_provider)
        add_token_to_provider(
            mock_oauth_provider, "no_expiry_token", no_expiry_access_token
        )
        request = Request(
            {
                "type": "http",
                "headers": [(b"authorization", b"Bearer no_expiry_token")],
            }
        )
        result = await backend.authenticate(request)
        assert result is not None
        credentials, user = result
        assert isinstance(credentials, AuthCredentials)
        assert isinstance(user, AuthenticatedUser)
        assert credentials.scopes == ["read", "write"]
        assert user.display_name == "test_client"
        assert user.access_token == no_expiry_access_token
        assert user.scopes == ["read", "write"]


@pytest.mark.anyio
class TestRequireAuthMiddleware:
    """Tests for the RequireAuthMiddleware class."""

    async def test_no_user(self):
        """Test middleware with no user in scope."""
        app = MockApp()
        middleware = RequireAuthMiddleware(app, required_scopes=["read"])
        scope: Scope = {"type": "http"}

        # Create dummy async functions for receive and send
        async def receive() -> Message:
            return {"type": "http.request"}

        async def send(message: Message) -> None:
            pass

        with pytest.raises(HTTPException) as excinfo:
            await middleware(scope, receive, send)

        assert excinfo.value.status_code == 401
        assert excinfo.value.detail == "Unauthorized"
        assert not app.called

    async def test_non_authenticated_user(self):
        """Test middleware with non-authenticated user in scope."""
        app = MockApp()
        middleware = RequireAuthMiddleware(app, required_scopes=["read"])
        scope: Scope = {"type": "http", "user": object()}

        # Create dummy async functions for receive and send
        async def receive() -> Message:
            return {"type": "http.request"}

        async def send(message: Message) -> None:
            pass

        with pytest.raises(HTTPException) as excinfo:
            await middleware(scope, receive, send)

        assert excinfo.value.status_code == 401
        assert excinfo.value.detail == "Unauthorized"
        assert not app.called

    async def test_missing_required_scope(self, valid_access_token: AccessToken):
        """Test middleware with user missing required scope."""
        app = MockApp()
        middleware = RequireAuthMiddleware(app, required_scopes=["admin"])

        # Create a user with read/write scopes but not admin
        user = AuthenticatedUser(valid_access_token)
        auth = AuthCredentials(["read", "write"])

        scope: Scope = {"type": "http", "user": user, "auth": auth}

        # Create dummy async functions for receive and send
        async def receive() -> Message:
            return {"type": "http.request"}

        async def send(message: Message) -> None:
            pass

        with pytest.raises(HTTPException) as excinfo:
            await middleware(scope, receive, send)

        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == "Insufficient scope"
        assert not app.called

    async def test_no_auth_credentials(self, valid_access_token: AccessToken):
        """Test middleware with no auth credentials in scope."""
        app = MockApp()
        middleware = RequireAuthMiddleware(app, required_scopes=["read"])

        # Create a user with read/write scopes
        user = AuthenticatedUser(valid_access_token)

        scope: Scope = {"type": "http", "user": user}  # No auth credentials

        # Create dummy async functions for receive and send
        async def receive() -> Message:
            return {"type": "http.request"}

        async def send(message: Message) -> None:
            pass

        with pytest.raises(HTTPException) as excinfo:
            await middleware(scope, receive, send)

        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == "Insufficient scope"
        assert not app.called

    async def test_has_required_scopes(self, valid_access_token: AccessToken):
        """Test middleware with user having all required scopes."""
        app = MockApp()
        middleware = RequireAuthMiddleware(app, required_scopes=["read"])

        # Create a user with read/write scopes
        user = AuthenticatedUser(valid_access_token)
        auth = AuthCredentials(["read", "write"])

        scope: Scope = {"type": "http", "user": user, "auth": auth}

        # Create dummy async functions for receive and send
        async def receive() -> Message:
            return {"type": "http.request"}

        async def send(message: Message) -> None:
            pass

        await middleware(scope, receive, send)

        assert app.called
        assert app.scope == scope
        assert app.receive == receive
        assert app.send == send

    async def test_multiple_required_scopes(self, valid_access_token: AccessToken):
        """Test middleware with multiple required scopes."""
        app = MockApp()
        middleware = RequireAuthMiddleware(app, required_scopes=["read", "write"])

        # Create a user with read/write scopes
        user = AuthenticatedUser(valid_access_token)
        auth = AuthCredentials(["read", "write"])

        scope: Scope = {"type": "http", "user": user, "auth": auth}

        # Create dummy async functions for receive and send
        async def receive() -> Message:
            return {"type": "http.request"}

        async def send(message: Message) -> None:
            pass

        await middleware(scope, receive, send)

        assert app.called
        assert app.scope == scope
        assert app.receive == receive
        assert app.send == send

    async def test_no_required_scopes(self, valid_access_token: AccessToken):
        """Test middleware with no required scopes."""
        app = MockApp()
        middleware = RequireAuthMiddleware(app, required_scopes=[])

        # Create a user with read/write scopes
        user = AuthenticatedUser(valid_access_token)
        auth = AuthCredentials(["read", "write"])

        scope: Scope = {"type": "http", "user": user, "auth": auth}

        # Create dummy async functions for receive and send
        async def receive() -> Message:
            return {"type": "http.request"}

        async def send(message: Message) -> None:
            pass

        await middleware(scope, receive, send)

        assert app.called
        assert app.scope == scope
        assert app.receive == receive
        assert app.send == send
