"""
Tests for the TokenHandler.
"""

import base64
import hashlib
import time
from typing import Any, cast

import pytest
from pydantic import AnyUrl
from starlette.requests import Request
from starlette.types import Message, Scope

from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class MockOAuthProvider:
    """Mock OAuth provider for testing."""

    def __init__(self):
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.authorization_codes: dict[str, AuthorizationCode] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}
        self.access_tokens: dict[str, AccessToken] = {}

    def add_client(self, client: OAuthClientInformationFull) -> None:
        """Add a client to the provider."""
        if client.client_id:
            self.clients[client.client_id] = client

    def add_authorization_code(self, code: str, auth_code: AuthorizationCode) -> None:
        """Add an authorization code."""
        self.authorization_codes[code] = auth_code

    def add_refresh_token(self, token: str, refresh_token: RefreshToken) -> None:
        """Add a refresh token."""
        self.refresh_tokens[token] = refresh_token

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Get client by ID."""
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Register a client (not used in these tests)."""
        pass  # pragma: no cover

    async def authorize(self, client: OAuthClientInformationFull, params: Any) -> str:
        """Authorize a client (not used in these tests)."""
        return ""  # pragma: no cover

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        """Load authorization code."""
        return self.authorization_codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Exchange authorization code for tokens."""
        return OAuthToken(
            access_token="mock_access_token",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="mock_refresh_token",
        )

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        """Load refresh token."""
        return self.refresh_tokens.get(refresh_token)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchange refresh token for new tokens."""
        return OAuthToken(
            access_token="mock_new_access_token",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="mock_new_refresh_token",
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Load an access token."""
        return self.access_tokens.get(token)  # pragma: no cover

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Revoke a token (not used in these tests)."""
        pass  # pragma: no cover


class MockClientAuthenticator:
    """Mock client authenticator for testing."""

    def __init__(self):
        self.should_fail = False
        self.client_to_return: OAuthClientInformationFull | None = None

    async def authenticate_request(self, request: Request) -> OAuthClientInformationFull:
        """Authenticate a client request."""
        if self.should_fail:
            raise AuthenticationError("Authentication failed")
        if self.client_to_return is None:
            raise AuthenticationError("No client configured")
        return self.client_to_return


def create_mock_request(form_data: dict[str, str], headers: dict[str, str] | None = None) -> Request:
    """Create a mock Starlette Request with form data and headers."""
    raw_headers: list[tuple[bytes, bytes]] = []
    if headers:
        for key, value in headers.items():
            raw_headers.append((key.lower().encode(), value.encode()))
    
    raw_headers.append((b"content-type", b"application/x-www-form-urlencoded"))

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "headers": raw_headers,
    }

    # Create a simple receive callable that returns form data
    messages: list[Message] = []

    # Encode form data
    encoded_body = "&".join(f"{k}={v}" for k, v in form_data.items()).encode()
    messages.append(
        {
            "type": "http.request",
            "body": encoded_body,
        }
    )

    async def receive() -> Message:
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    request = Request(scope, receive)
    return request


def generate_code_verifier() -> str:
    """Generate a PKCE code verifier."""
    return "test_code_verifier_with_sufficient_length_for_pkce_validation"


def generate_code_challenge(verifier: str) -> str:
    """Generate a PKCE code challenge from a verifier."""
    sha256 = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(sha256).decode().rstrip("=")


@pytest.fixture
def mock_oauth_provider() -> OAuthAuthorizationServerProvider[Any, Any, Any]:
    """Create a mock OAuth provider."""
    return cast(OAuthAuthorizationServerProvider[Any, Any, Any], MockOAuthProvider())


@pytest.fixture
def mock_client_authenticator() -> ClientAuthenticator:
    """Create a mock client authenticator."""
    return cast(ClientAuthenticator, MockClientAuthenticator())


@pytest.fixture
def test_client() -> OAuthClientInformationFull:
    """Create a test client."""
    return OAuthClientInformationFull(
        client_id="test_client",
        client_secret="test_secret",
        redirect_uris=[AnyUrl("https://example.com/callback")],
        token_endpoint_auth_method="client_secret_basic",
        grant_types=["authorization_code", "refresh_token"],
    )


@pytest.mark.anyio
class TestTokenHandlerAuthBasic:
    """Tests for TokenHandler with Auth Basic header."""

    async def test_auth_basic_without_form_client_credentials(
        self,
        mock_oauth_provider: OAuthAuthorizationServerProvider[Any, Any, Any],
        test_client: OAuthClientInformationFull,
    ):
        """Test token request with Auth Basic header but no client_id/client_secret in form data.

        This test validates the scenario where:
        - The client uses HTTP Basic authentication (Authorization: Basic header)
        - The form data does NOT include client_id or client_secret fields
        - The handler should response correctly

        Note: This test may fail if the current implementation does not properly
        handle the case where client_id is missing from form_data.
        """
        # Setup provider
        provider = cast(MockOAuthProvider, mock_oauth_provider)
        provider.add_client(test_client)
        # Create REAL authenticator (not mock) to test actual behavior
        authenticator = ClientAuthenticator(provider=provider)

        # Create handler
        handler = TokenHandler(provider=provider, client_authenticator=authenticator)

        # Generate PKCE values
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)

        # Add authorization code to provider
        auth_code = AuthorizationCode(
            code="test_auth_code",
            scopes=["read", "write"],
            expires_at=time.time() + 600,  # 10 minutes from now
            client_id="test_client",
            code_challenge=code_challenge,
            redirect_uri=AnyUrl("https://example.com/callback"),
            redirect_uri_provided_explicitly=True,
        )
        provider.add_authorization_code("test_auth_code", auth_code)

        # Create Basic auth header
        credentials = f"{test_client.client_id}:{test_client.client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        auth_header = f"Basic {encoded_credentials}"

        # Create form data WITHOUT client_id and client_secret
        form_data = {
            "grant_type": "authorization_code",
            "code": "test_auth_code",
            "redirect_uri": "https://example.com/callback",
            "code_verifier": code_verifier,
        }

        # Create request with Auth Basic header
        request = create_mock_request(form_data, headers={"Authorization": auth_header})

        # Execute the handler
        response = await handler.handle(request)


        # Validate the response
        # Note: This test may fail if client_id is not extracted from the Basic auth header
        # or form_data, since the handler expects client_id in the form_data
        assert response is not None

        if response.status_code != 200:
            # If not successful, print the response body for debugging
            body_bytes = bytes(response.body)
            body = body_bytes.decode()
            pytest.fail(f"Handler response error: {body}")

