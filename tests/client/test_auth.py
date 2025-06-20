"""
Tests for refactored OAuth client authentication implementation.
"""

import time

import httpx
import pytest
from pydantic import AnyHttpUrl, AnyUrl

from mcp.client.auth import OAuthClientProvider, PKCEParameters
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)


class MockTokenStorage:
    """Mock token storage for testing."""

    def __init__(self):
        self._tokens: OAuthToken | None = None
        self._client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info


@pytest.fixture
def mock_storage():
    return MockTokenStorage()


@pytest.fixture
def client_metadata():
    return OAuthClientMetadata(
        client_name="Test Client",
        client_uri=AnyHttpUrl("https://example.com"),
        redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        scope="read write",
    )


@pytest.fixture
def valid_tokens():
    return OAuthToken(
        access_token="test_access_token",
        token_type="Bearer",
        expires_in=3600,
        refresh_token="test_refresh_token",
        scope="read write",
    )


@pytest.fixture
def oauth_provider(client_metadata, mock_storage):
    async def redirect_handler(url: str) -> None:
        """Mock redirect handler."""
        pass

    async def callback_handler() -> tuple[str, str | None]:
        """Mock callback handler."""
        return "test_auth_code", "test_state"

    return OAuthClientProvider(
        server_url="https://api.example.com/v1/mcp",
        client_metadata=client_metadata,
        storage=mock_storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


class TestPKCEParameters:
    """Test PKCE parameter generation."""

    def test_pkce_generation(self):
        """Test PKCE parameter generation creates valid values."""
        pkce = PKCEParameters.generate()

        # Verify lengths
        assert len(pkce.code_verifier) == 128
        assert 43 <= len(pkce.code_challenge) <= 128

        # Verify characters used in verifier
        allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        assert all(c in allowed_chars for c in pkce.code_verifier)

        # Verify base64url encoding in challenge (no padding)
        assert "=" not in pkce.code_challenge

    def test_pkce_uniqueness(self):
        """Test PKCE generates unique values each time."""
        pkce1 = PKCEParameters.generate()
        pkce2 = PKCEParameters.generate()

        assert pkce1.code_verifier != pkce2.code_verifier
        assert pkce1.code_challenge != pkce2.code_challenge


class TestOAuthContext:
    """Test OAuth context functionality."""

    @pytest.mark.anyio
    async def test_oauth_provider_initialization(self, oauth_provider, client_metadata, mock_storage):
        """Test OAuthClientProvider basic setup."""
        assert oauth_provider.context.server_url == "https://api.example.com/v1/mcp"
        assert oauth_provider.context.client_metadata == client_metadata
        assert oauth_provider.context.storage == mock_storage
        assert oauth_provider.context.timeout == 300.0
        assert oauth_provider.context is not None

    def test_context_url_parsing(self, oauth_provider):
        """Test get_authorization_base_url() extracts base URLs correctly."""
        context = oauth_provider.context

        # Test with path
        assert context.get_authorization_base_url("https://api.example.com/v1/mcp") == "https://api.example.com"

        # Test with no path
        assert context.get_authorization_base_url("https://api.example.com") == "https://api.example.com"

        # Test with port
        assert (
            context.get_authorization_base_url("https://api.example.com:8080/path/to/mcp")
            == "https://api.example.com:8080"
        )

        # Test with query params
        assert (
            context.get_authorization_base_url("https://api.example.com/path?param=value") == "https://api.example.com"
        )

    @pytest.mark.anyio
    async def test_token_validity_checking(self, oauth_provider, mock_storage, valid_tokens):
        """Test is_token_valid() and can_refresh_token() logic."""
        context = oauth_provider.context

        # No tokens - should be invalid
        assert not context.is_token_valid()
        assert not context.can_refresh_token()

        # Set valid tokens and client info
        context.current_tokens = valid_tokens
        context.token_expiry_time = time.time() + 1800  # 30 minutes from now
        context.client_info = OAuthClientInformationFull(
            client_id="test_client_id",
            client_secret="test_client_secret",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        )

        # Should be valid
        assert context.is_token_valid()
        assert context.can_refresh_token()  # Has refresh token and client info

        # Expire the token
        context.token_expiry_time = time.time() - 100  # Expired 100 seconds ago
        assert not context.is_token_valid()
        assert context.can_refresh_token()  # Can still refresh

        # Remove refresh token
        context.current_tokens.refresh_token = None
        assert not context.can_refresh_token()

        # Remove client info
        context.current_tokens.refresh_token = "test_refresh_token"
        context.client_info = None
        assert not context.can_refresh_token()

    def test_clear_tokens(self, oauth_provider, valid_tokens):
        """Test clear_tokens() removes token data."""
        context = oauth_provider.context
        context.current_tokens = valid_tokens
        context.token_expiry_time = time.time() + 1800

        # Clear tokens
        context.clear_tokens()

        # Verify cleared
        assert context.current_tokens is None
        assert context.token_expiry_time is None


class TestOAuthFlow:
    """Test OAuth flow methods."""

    @pytest.mark.anyio
    async def test_discover_protected_resource_request(self, oauth_provider):
        """Test protected resource discovery request building."""
        request = await oauth_provider._discover_protected_resource()

        assert request.method == "GET"
        assert str(request.url) == "https://api.example.com/.well-known/oauth-protected-resource"
        assert "mcp-protocol-version" in request.headers

    @pytest.mark.anyio
    async def test_discover_oauth_metadata_request(self, oauth_provider):
        """Test OAuth metadata discovery request building."""
        request = await oauth_provider._discover_oauth_metadata()

        assert request.method == "GET"
        assert str(request.url) == "https://api.example.com/.well-known/oauth-authorization-server"
        assert "mcp-protocol-version" in request.headers

    @pytest.mark.anyio
    async def test_register_client_request(self, oauth_provider):
        """Test client registration request building."""
        request = await oauth_provider._register_client()

        assert request is not None
        assert request.method == "POST"
        assert str(request.url) == "https://api.example.com/register"
        assert request.headers["Content-Type"] == "application/json"

    @pytest.mark.anyio
    async def test_register_client_skip_if_registered(self, oauth_provider, mock_storage):
        """Test client registration is skipped if already registered."""
        # Set existing client info
        client_info = OAuthClientInformationFull(
            client_id="existing_client",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        )
        oauth_provider.context.client_info = client_info

        # Should return None (skip registration)
        request = await oauth_provider._register_client()
        assert request is None

    @pytest.mark.anyio
    async def test_token_exchange_request(self, oauth_provider):
        """Test token exchange request building."""
        # Set up required context
        oauth_provider.context.client_info = OAuthClientInformationFull(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        )

        request = await oauth_provider._exchange_token("test_auth_code", "test_verifier")

        assert request.method == "POST"
        assert str(request.url) == "https://api.example.com/token"
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"

        # Check form data
        content = request.content.decode()
        assert "grant_type=authorization_code" in content
        assert "code=test_auth_code" in content
        assert "code_verifier=test_verifier" in content
        assert "client_id=test_client" in content
        assert "client_secret=test_secret" in content
        # Resource parameter should be included per RFC 8707
        assert "resource=https%3A%2F%2Fapi.example.com%2Fv1%2Fmcp" in content

    @pytest.mark.anyio
    async def test_authorization_url_request(self, oauth_provider):
        """Test authorization URL construction with resource parameter."""
        from unittest.mock import patch

        # Set up required context
        oauth_provider.context.client_info = OAuthClientInformationFull(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        )

        # Mock the redirect handler to capture the URL
        captured_url = None

        async def mock_redirect_handler(url: str):
            nonlocal captured_url
            captured_url = url

        oauth_provider.context.redirect_handler = mock_redirect_handler

        # Mock callback handler
        async def mock_callback_handler():
            return "test_auth_code", "test_state"

        oauth_provider.context.callback_handler = mock_callback_handler

        # Mock pkce and state generation for predictable testing
        with (
            patch("mcp.client.auth.PKCEParameters.generate") as mock_pkce,
            patch("mcp.client.auth.secrets.token_urlsafe") as mock_state,
        ):
            mock_pkce.return_value.code_verifier = "test_verifier"
            mock_pkce.return_value.code_challenge = "test_challenge"
            mock_state.return_value = "test_state"

            # Mock compare_digest to return True
            with patch("mcp.client.auth.secrets.compare_digest", return_value=True):
                await oauth_provider._perform_authorization()

        # Verify the captured URL contains resource parameter
        assert captured_url is not None
        assert "resource=https%3A%2F%2Fapi.example.com%2Fv1%2Fmcp" in captured_url
        assert "client_id=test_client" in captured_url
        assert "response_type=code" in captured_url
        assert "code_challenge=test_challenge" in captured_url
        assert "code_challenge_method=S256" in captured_url

    @pytest.mark.anyio
    async def test_refresh_token_request(self, oauth_provider, valid_tokens):
        """Test refresh token request building."""
        # Set up required context
        oauth_provider.context.current_tokens = valid_tokens
        oauth_provider.context.client_info = OAuthClientInformationFull(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        )

        request = await oauth_provider._refresh_token()

        assert request.method == "POST"
        assert str(request.url) == "https://api.example.com/token"
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"

        # Check form data
        content = request.content.decode()
        assert "grant_type=refresh_token" in content
        assert "refresh_token=test_refresh_token" in content
        assert "client_id=test_client" in content
        assert "client_secret=test_secret" in content
        # Resource parameter should be included per RFC 8707
        assert "resource=https%3A%2F%2Fapi.example.com%2Fv1%2Fmcp" in content


class TestAuthFlow:
    """Test the auth flow in httpx."""

    @pytest.mark.anyio
    async def test_auth_flow_with_valid_tokens(self, oauth_provider, mock_storage, valid_tokens):
        """Test auth flow when tokens are already valid."""
        # Pre-store valid tokens
        await mock_storage.set_tokens(valid_tokens)
        oauth_provider.context.current_tokens = valid_tokens
        oauth_provider.context.token_expiry_time = time.time() + 1800
        oauth_provider._initialized = True

        # Create a test request
        test_request = httpx.Request("GET", "https://api.example.com/test")

        # Mock the auth flow
        auth_flow = oauth_provider.async_auth_flow(test_request)

        # Should get the request with auth header added
        request = await auth_flow.__anext__()
        assert request.headers["Authorization"] == "Bearer test_access_token"

        # Send a successful response
        response = httpx.Response(200)
        try:
            await auth_flow.asend(response)
        except StopAsyncIteration:
            pass  # Expected
