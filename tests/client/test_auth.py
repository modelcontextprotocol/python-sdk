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
    ProtectedResourceMetadata,
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
        assert str(request.url) == "https://api.example.com/.well-known/oauth-authorization-server/v1/mcp"
        assert "mcp-protocol-version" in request.headers

    @pytest.mark.anyio
    async def test_discover_oauth_metadata_request_no_path(self, client_metadata, mock_storage):
        """Test OAuth metadata discovery request building when server has no path."""

        async def redirect_handler(url: str) -> None:
            pass

        async def callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "test_state"

        provider = OAuthClientProvider(
            server_url="https://api.example.com",
            client_metadata=client_metadata,
            storage=mock_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

        request = await provider._discover_oauth_metadata()

        assert request.method == "GET"
        assert str(request.url) == "https://api.example.com/.well-known/oauth-authorization-server"
        assert "mcp-protocol-version" in request.headers

    @pytest.mark.anyio
    async def test_discover_oauth_metadata_request_trailing_slash(self, client_metadata, mock_storage):
        """Test OAuth metadata discovery request building when server path has trailing slash."""

        async def redirect_handler(url: str) -> None:
            pass

        async def callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "test_state"

        provider = OAuthClientProvider(
            server_url="https://api.example.com/v1/mcp/",
            client_metadata=client_metadata,
            storage=mock_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

        request = await provider._discover_oauth_metadata()

        assert request.method == "GET"
        assert str(request.url) == "https://api.example.com/.well-known/oauth-authorization-server/v1/mcp"
        assert "mcp-protocol-version" in request.headers


class TestOAuthFallback:
    """Test OAuth discovery fallback behavior for legacy (act as AS not RS) servers."""

    @pytest.mark.anyio
    async def test_fallback_discovery_request(self, client_metadata, mock_storage):
        """Test fallback discovery request building."""

        async def redirect_handler(url: str) -> None:
            pass

        async def callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "test_state"

        provider = OAuthClientProvider(
            server_url="https://api.example.com/v1/mcp",
            client_metadata=client_metadata,
            storage=mock_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

        # Set up discovery state manually as if path-aware discovery was attempted
        provider.context.discovery_base_url = "https://api.example.com"
        provider.context.discovery_pathname = "/v1/mcp"

        # Test fallback request building
        request = await provider._discover_oauth_metadata_fallback()

        assert request.method == "GET"
        assert str(request.url) == "https://api.example.com/.well-known/oauth-authorization-server"
        assert "mcp-protocol-version" in request.headers

    @pytest.mark.anyio
    async def test_should_attempt_fallback(self, oauth_provider):
        """Test fallback decision logic."""
        # Should attempt fallback on 404 with non-root path
        assert oauth_provider._should_attempt_fallback(404, "/v1/mcp")

        # Should NOT attempt fallback on 404 with root path
        assert not oauth_provider._should_attempt_fallback(404, "/")

        # Should NOT attempt fallback on other status codes
        assert not oauth_provider._should_attempt_fallback(200, "/v1/mcp")
        assert not oauth_provider._should_attempt_fallback(500, "/v1/mcp")

    @pytest.mark.anyio
    async def test_handle_metadata_response_success(self, oauth_provider):
        """Test successful metadata response handling."""
        # Create minimal valid OAuth metadata
        content = b"""{
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize", 
            "token_endpoint": "https://auth.example.com/token"
        }"""
        response = httpx.Response(200, content=content)

        # Should return True (success) and set metadata
        result = await oauth_provider._handle_oauth_metadata_response(response, is_fallback=False)
        assert result is True
        assert oauth_provider.context.oauth_metadata is not None
        assert str(oauth_provider.context.oauth_metadata.issuer) == "https://auth.example.com/"

    @pytest.mark.anyio
    async def test_handle_metadata_response_404_needs_fallback(self, oauth_provider):
        """Test 404 response handling that should trigger fallback."""
        # Set up discovery state for non-root path
        oauth_provider.context.discovery_base_url = "https://api.example.com"
        oauth_provider.context.discovery_pathname = "/v1/mcp"

        # Mock 404 response
        response = httpx.Response(404)

        # Should return False (needs fallback)
        result = await oauth_provider._handle_oauth_metadata_response(response, is_fallback=False)
        assert result is False

    @pytest.mark.anyio
    async def test_handle_metadata_response_404_no_fallback_needed(self, oauth_provider):
        """Test 404 response handling when no fallback is needed."""
        # Set up discovery state for root path
        oauth_provider.context.discovery_base_url = "https://api.example.com"
        oauth_provider.context.discovery_pathname = "/"

        # Mock 404 response
        response = httpx.Response(404)

        # Should return True (no fallback needed)
        result = await oauth_provider._handle_oauth_metadata_response(response, is_fallback=False)
        assert result is True

    @pytest.mark.anyio
    async def test_handle_metadata_response_404_fallback_attempt(self, oauth_provider):
        """Test 404 response handling during fallback attempt."""
        # Mock 404 response during fallback
        response = httpx.Response(404)

        # Should return True (fallback attempt complete, no further action needed)
        result = await oauth_provider._handle_oauth_metadata_response(response, is_fallback=True)
        assert result is True

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


class TestProtectedResourceMetadata:
    """Test protected resource handling."""

    @pytest.mark.anyio
    async def test_resource_param_included_with_recent_protocol_version(self, oauth_provider: OAuthClientProvider):
        """Test resource parameter is included for protocol version >= 2025-06-18."""
        # Set protocol version to 2025-06-18
        oauth_provider.context.protocol_version = "2025-06-18"
        oauth_provider.context.client_info = OAuthClientInformationFull(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        )

        # Test in token exchange
        request = await oauth_provider._exchange_token("test_code", "test_verifier")
        content = request.content.decode()
        assert "resource=" in content
        # Check URL-encoded resource parameter
        from urllib.parse import quote

        expected_resource = quote(oauth_provider.context.get_resource_url(), safe="")
        assert f"resource={expected_resource}" in content

        # Test in refresh token
        oauth_provider.context.current_tokens = OAuthToken(
            access_token="test_access",
            token_type="Bearer",
            refresh_token="test_refresh",
        )
        refresh_request = await oauth_provider._refresh_token()
        refresh_content = refresh_request.content.decode()
        assert "resource=" in refresh_content

    @pytest.mark.anyio
    async def test_resource_param_excluded_with_old_protocol_version(self, oauth_provider: OAuthClientProvider):
        """Test resource parameter is excluded for protocol version < 2025-06-18."""
        # Set protocol version to older version
        oauth_provider.context.protocol_version = "2025-03-26"
        oauth_provider.context.client_info = OAuthClientInformationFull(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        )

        # Test in token exchange
        request = await oauth_provider._exchange_token("test_code", "test_verifier")
        content = request.content.decode()
        assert "resource=" not in content

        # Test in refresh token
        oauth_provider.context.current_tokens = OAuthToken(
            access_token="test_access",
            token_type="Bearer",
            refresh_token="test_refresh",
        )
        refresh_request = await oauth_provider._refresh_token()
        refresh_content = refresh_request.content.decode()
        assert "resource=" not in refresh_content

    @pytest.mark.anyio
    async def test_resource_param_included_with_protected_resource_metadata(self, oauth_provider: OAuthClientProvider):
        """Test resource parameter is always included when protected resource metadata exists."""
        # Set old protocol version but with protected resource metadata
        oauth_provider.context.protocol_version = "2025-03-26"
        oauth_provider.context.protected_resource_metadata = ProtectedResourceMetadata(
            resource=AnyHttpUrl("https://api.example.com/v1/mcp"),
            authorization_servers=[AnyHttpUrl("https://api.example.com")],
        )
        oauth_provider.context.client_info = OAuthClientInformationFull(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        )

        # Test in token exchange
        request = await oauth_provider._exchange_token("test_code", "test_verifier")
        content = request.content.decode()
        assert "resource=" in content


class TestRegistrationResponse:
    """Test client registration response handling."""

    @pytest.mark.anyio
    async def test_handle_registration_response_reads_before_accessing_text(self, oauth_provider):
        """Test that response.aread() is called before accessing response.text."""

        # Track if aread() was called
        class MockResponse:
            def __init__(self):
                self.status_code = 400
                self._aread_called = False
                self._text = "Registration failed with error"

            async def aread(self):
                self._aread_called = True
                return b"test content"

            @property
            def text(self):
                if not self._aread_called:
                    raise RuntimeError("Response.text accessed before response.aread()")
                return self._text

        mock_response = MockResponse()

        # This should call aread() before accessing text
        with pytest.raises(Exception) as exc_info:
            await oauth_provider._handle_registration_response(mock_response)

        # Verify aread() was called
        assert mock_response._aread_called
        # Verify the error message includes the response text
        assert "Registration failed: 400" in str(exc_info.value)


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
