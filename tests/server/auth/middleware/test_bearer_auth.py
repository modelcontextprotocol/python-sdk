"""Tests for the BearerAuth middleware components."""

import time
from typing import Any, cast

import pytest
from starlette.authentication import AuthCredentials
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import Message, Receive, Scope, Send

from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser, BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken, OAuthAuthorizationServerProvider, ProviderTokenVerifier


class MockOAuthProvider:
    def __init__(self):
        self.tokens: dict[str, AccessToken] = {}

    def add_token(self, token: str, access_token: AccessToken) -> None:
        self.tokens[token] = access_token

    async def load_access_token(self, token: str) -> AccessToken | None:
        return self.tokens.get(token)


def add_token_to_provider(
    provider: OAuthAuthorizationServerProvider[Any, Any, Any],
    token: str,
    access_token: AccessToken,
) -> None:
    """Add a token, casting around the fixture's abstract provider type."""
    mock_provider = cast(MockOAuthProvider, provider)
    mock_provider.add_token(token, access_token)


class MockApp:
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
    return cast(OAuthAuthorizationServerProvider[Any, Any, Any], MockOAuthProvider())


@pytest.fixture
def valid_access_token() -> AccessToken:
    return AccessToken(
        token="valid_token",
        client_id="test_client",
        scopes=["read", "write"],
        expires_at=int(time.time()) + 3600,
    )


@pytest.fixture
def expired_access_token() -> AccessToken:
    return AccessToken(
        token="expired_token",
        client_id="test_client",
        scopes=["read"],
        expires_at=int(time.time()) - 3600,
    )


@pytest.fixture
def no_expiry_access_token() -> AccessToken:
    return AccessToken(
        token="no_expiry_token",
        client_id="test_client",
        scopes=["read", "write"],
        expires_at=None,
    )


@pytest.mark.anyio
class TestBearerAuthBackend:
    async def test_no_auth_header(self, mock_oauth_provider: OAuthAuthorizationServerProvider[Any, Any, Any]):
        backend = BearerAuthBackend(token_verifier=ProviderTokenVerifier(mock_oauth_provider))
        request = Request({"type": "http", "headers": []})
        result = await backend.authenticate(request)
        assert result is None

    async def test_non_bearer_auth_header(self, mock_oauth_provider: OAuthAuthorizationServerProvider[Any, Any, Any]):
        backend = BearerAuthBackend(token_verifier=ProviderTokenVerifier(mock_oauth_provider))
        request = Request(
            {
                "type": "http",
                "headers": [(b"authorization", b"Basic dXNlcjpwYXNz")],
            }
        )
        result = await backend.authenticate(request)
        assert result is None

    async def test_invalid_token(self, mock_oauth_provider: OAuthAuthorizationServerProvider[Any, Any, Any]):
        backend = BearerAuthBackend(token_verifier=ProviderTokenVerifier(mock_oauth_provider))
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
        backend = BearerAuthBackend(token_verifier=ProviderTokenVerifier(mock_oauth_provider))
        add_token_to_provider(mock_oauth_provider, "expired_token", expired_access_token)
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
        backend = BearerAuthBackend(token_verifier=ProviderTokenVerifier(mock_oauth_provider))
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
        backend = BearerAuthBackend(token_verifier=ProviderTokenVerifier(mock_oauth_provider))
        add_token_to_provider(mock_oauth_provider, "no_expiry_token", no_expiry_access_token)
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

    async def test_lowercase_bearer_prefix(
        self,
        mock_oauth_provider: OAuthAuthorizationServerProvider[Any, Any, Any],
        valid_access_token: AccessToken,
    ):
        backend = BearerAuthBackend(token_verifier=ProviderTokenVerifier(mock_oauth_provider))
        add_token_to_provider(mock_oauth_provider, "valid_token", valid_access_token)
        headers = Headers({"Authorization": "bearer valid_token"})
        scope = {"type": "http", "headers": headers.raw}
        request = Request(scope)
        result = await backend.authenticate(request)
        assert result is not None
        credentials, user = result
        assert isinstance(credentials, AuthCredentials)
        assert isinstance(user, AuthenticatedUser)
        assert credentials.scopes == ["read", "write"]
        assert user.display_name == "test_client"
        assert user.access_token == valid_access_token

    async def test_mixed_case_bearer_prefix(
        self,
        mock_oauth_provider: OAuthAuthorizationServerProvider[Any, Any, Any],
        valid_access_token: AccessToken,
    ):
        backend = BearerAuthBackend(token_verifier=ProviderTokenVerifier(mock_oauth_provider))
        add_token_to_provider(mock_oauth_provider, "valid_token", valid_access_token)
        headers = Headers({"authorization": "BeArEr valid_token"})
        scope = {"type": "http", "headers": headers.raw}
        request = Request(scope)
        result = await backend.authenticate(request)
        assert result is not None
        credentials, user = result
        assert isinstance(credentials, AuthCredentials)
        assert isinstance(user, AuthenticatedUser)
        assert credentials.scopes == ["read", "write"]
        assert user.display_name == "test_client"
        assert user.access_token == valid_access_token

    async def test_mixed_case_authorization_header(
        self,
        mock_oauth_provider: OAuthAuthorizationServerProvider[Any, Any, Any],
        valid_access_token: AccessToken,
    ):
        backend = BearerAuthBackend(token_verifier=ProviderTokenVerifier(mock_oauth_provider))
        add_token_to_provider(mock_oauth_provider, "valid_token", valid_access_token)
        headers = Headers({"AuThOrIzAtIoN": "BeArEr valid_token"})
        scope = {"type": "http", "headers": headers.raw}
        request = Request(scope)
        result = await backend.authenticate(request)
        assert result is not None
        credentials, user = result
        assert isinstance(credentials, AuthCredentials)
        assert isinstance(user, AuthenticatedUser)
        assert credentials.scopes == ["read", "write"]
        assert user.display_name == "test_client"
        assert user.access_token == valid_access_token


@pytest.mark.anyio
class TestRequireAuthMiddleware:
    async def test_no_user(self):
        app = MockApp()
        middleware = RequireAuthMiddleware(app, required_scopes=["read"])
        scope: Scope = {"type": "http"}

        async def receive() -> Message:  # pragma: no cover
            return {"type": "http.request"}

        sent_messages: list[Message] = []

        async def send(message: Message) -> None:
            sent_messages.append(message)

        await middleware(scope, receive, send)

        assert len(sent_messages) == 2
        assert sent_messages[0]["type"] == "http.response.start"
        assert sent_messages[0]["status"] == 401
        assert any(h[0] == b"www-authenticate" for h in sent_messages[0]["headers"])
        assert not app.called

    async def test_non_authenticated_user(self):
        app = MockApp()
        middleware = RequireAuthMiddleware(app, required_scopes=["read"])
        scope: Scope = {"type": "http", "user": object()}

        async def receive() -> Message:  # pragma: no cover
            return {"type": "http.request"}

        sent_messages: list[Message] = []

        async def send(message: Message) -> None:
            sent_messages.append(message)

        await middleware(scope, receive, send)

        assert len(sent_messages) == 2
        assert sent_messages[0]["type"] == "http.response.start"
        assert sent_messages[0]["status"] == 401
        assert any(h[0] == b"www-authenticate" for h in sent_messages[0]["headers"])
        assert not app.called

    async def test_missing_required_scope(self, valid_access_token: AccessToken):
        app = MockApp()
        middleware = RequireAuthMiddleware(app, required_scopes=["admin"])

        user = AuthenticatedUser(valid_access_token)
        auth = AuthCredentials(["read", "write"])

        scope: Scope = {"type": "http", "user": user, "auth": auth}

        async def receive() -> Message:  # pragma: no cover
            return {"type": "http.request"}

        sent_messages: list[Message] = []

        async def send(message: Message) -> None:
            sent_messages.append(message)

        await middleware(scope, receive, send)

        assert len(sent_messages) == 2
        assert sent_messages[0]["type"] == "http.response.start"
        assert sent_messages[0]["status"] == 403
        assert any(h[0] == b"www-authenticate" for h in sent_messages[0]["headers"])
        assert not app.called

    async def test_no_auth_credentials(self, valid_access_token: AccessToken):
        app = MockApp()
        middleware = RequireAuthMiddleware(app, required_scopes=["read"])

        user = AuthenticatedUser(valid_access_token)

        scope: Scope = {"type": "http", "user": user}

        async def receive() -> Message:  # pragma: no cover
            return {"type": "http.request"}

        sent_messages: list[Message] = []

        async def send(message: Message) -> None:
            sent_messages.append(message)

        await middleware(scope, receive, send)

        assert len(sent_messages) == 2
        assert sent_messages[0]["type"] == "http.response.start"
        assert sent_messages[0]["status"] == 403
        assert any(h[0] == b"www-authenticate" for h in sent_messages[0]["headers"])
        assert not app.called

    async def test_has_required_scopes(self, valid_access_token: AccessToken):
        app = MockApp()
        middleware = RequireAuthMiddleware(app, required_scopes=["read"])

        user = AuthenticatedUser(valid_access_token)
        auth = AuthCredentials(["read", "write"])

        scope: Scope = {"type": "http", "user": user, "auth": auth}

        async def receive() -> Message:  # pragma: no cover
            return {"type": "http.request"}

        async def send(message: Message) -> None:  # pragma: no cover
            pass

        await middleware(scope, receive, send)

        assert app.called
        assert app.scope == scope
        assert app.receive == receive
        assert app.send == send

    async def test_multiple_required_scopes(self, valid_access_token: AccessToken):
        app = MockApp()
        middleware = RequireAuthMiddleware(app, required_scopes=["read", "write"])

        user = AuthenticatedUser(valid_access_token)
        auth = AuthCredentials(["read", "write"])

        scope: Scope = {"type": "http", "user": user, "auth": auth}

        async def receive() -> Message:  # pragma: no cover
            return {"type": "http.request"}

        async def send(message: Message) -> None:  # pragma: no cover
            pass

        await middleware(scope, receive, send)

        assert app.called
        assert app.scope == scope
        assert app.receive == receive
        assert app.send == send

    async def test_no_required_scopes(self, valid_access_token: AccessToken):
        app = MockApp()
        middleware = RequireAuthMiddleware(app, required_scopes=[])

        user = AuthenticatedUser(valid_access_token)
        auth = AuthCredentials(["read", "write"])

        scope: Scope = {"type": "http", "user": user, "auth": auth}

        async def receive() -> Message:  # pragma: no cover
            return {"type": "http.request"}

        async def send(message: Message) -> None:  # pragma: no cover
            pass

        await middleware(scope, receive, send)

        assert app.called
        assert app.scope == scope
        assert app.receive == receive
        assert app.send == send
