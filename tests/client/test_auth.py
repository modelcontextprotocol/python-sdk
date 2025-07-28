"""
Tests for refactored OAuth client authentication implementation.
"""

import time
from unittest import mock

import httpx
import pytest
from inline_snapshot import Is, snapshot
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
    async def test_discover_protected_resource_request(self, client_metadata, mock_storage):
        """Test protected resource discovery request building maintains backward compatibility."""

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

        # Test without WWW-Authenticate (fallback)
        init_response = httpx.Response(
            status_code=401, headers={}, request=httpx.Request("GET", "https://request-api.example.com")
        )

        request = await provider._discover_protected_resource(init_response)
        assert request.method == "GET"
        assert str(request.url) == "https://api.example.com/.well-known/oauth-protected-resource"
        assert "mcp-protocol-version" in request.headers

        # Test with WWW-Authenticate header
        init_response.headers["WWW-Authenticate"] = (
            'Bearer resource_metadata="https://prm.example.com/.well-known/oauth-protected-resource/path"'
        )

        request = await provider._discover_protected_resource(init_response)
        assert request.method == "GET"
        assert str(request.url) == "https://prm.example.com/.well-known/oauth-protected-resource/path"
        assert "mcp-protocol-version" in request.headers

    @pytest.mark.anyio
    def test_create_oauth_metadata_request(self, oauth_provider):
        """Test OAuth metadata discovery request building."""
        request = oauth_provider._create_oauth_metadata_request("https://example.com")

        # Ensure correct method and headers, and that the URL is unmodified
        assert request.method == "GET"
        assert str(request.url) == "https://example.com"
        assert "mcp-protocol-version" in request.headers


class TestOAuthFallback:
    """Test OAuth discovery fallback behavior for legacy (act as AS not RS) servers."""

    @pytest.mark.anyio
    async def test_oauth_discovery_fallback_order(self, oauth_provider):
        """Test fallback URL construction order."""
        discovery_urls = oauth_provider._get_discovery_urls()

        assert discovery_urls == [
            "https://api.example.com/.well-known/oauth-authorization-server/v1/mcp",
            "https://api.example.com/.well-known/oauth-authorization-server",
            "https://api.example.com/.well-known/openid-configuration/v1/mcp",
            "https://api.example.com/v1/mcp/.well-known/openid-configuration",
        ]

    @pytest.mark.anyio
    async def test_oauth_discovery_fallback_conditions(self, oauth_provider):
        """Test the conditions during which an AS metadata discovery fallback will be attempted."""
        # Ensure no tokens are stored
        oauth_provider.context.current_tokens = None
        oauth_provider.context.token_expiry_time = None
        oauth_provider._initialized = True

        # Mock client info to skip DCR
        oauth_provider.context.client_info = OAuthClientInformationFull(
            client_id="existing_client",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        )

        # Create a test request
        test_request = httpx.Request("GET", "https://api.example.com/v1/mcp")

        # Mock the auth flow
        auth_flow = oauth_provider.async_auth_flow(test_request)

        # First request should be the original request without auth header
        request = await auth_flow.__anext__()
        assert "Authorization" not in request.headers

        # Send a 401 response to trigger the OAuth flow
        response = httpx.Response(
            401,
            headers={
                "WWW-Authenticate": 'Bearer resource_metadata="https://api.example.com/.well-known/oauth-protected-resource"'
            },
            request=test_request,
        )

        # Next request should be to discover protected resource metadata
        discovery_request = await auth_flow.asend(response)
        assert str(discovery_request.url) == "https://api.example.com/.well-known/oauth-protected-resource"
        assert discovery_request.method == "GET"

        # Send a successful discovery response with minimal protected resource metadata
        discovery_response = httpx.Response(
            200,
            content=b'{"resource": "https://api.example.com/v1/mcp", "authorization_servers": ["https://auth.example.com/v1/mcp"]}',
            request=discovery_request,
        )

        # Next request should be to discover OAuth metadata
        oauth_metadata_request_1 = await auth_flow.asend(discovery_response)
        assert (
            str(oauth_metadata_request_1.url)
            == "https://auth.example.com/.well-known/oauth-authorization-server/v1/mcp"
        )
        assert oauth_metadata_request_1.method == "GET"

        # Send a 404 response
        oauth_metadata_response_1 = httpx.Response(
            404,
            content=b"Not Found",
            request=oauth_metadata_request_1,
        )

        # Next request should be to discover OAuth metadata at the next endpoint
        oauth_metadata_request_2 = await auth_flow.asend(oauth_metadata_response_1)
        assert str(oauth_metadata_request_2.url) == "https://auth.example.com/.well-known/oauth-authorization-server"
        assert oauth_metadata_request_2.method == "GET"

        # Send a 400 response
        oauth_metadata_response_2 = httpx.Response(
            400,
            content=b"Bad Request",
            request=oauth_metadata_request_2,
        )

        # Next request should be to discover OAuth metadata at the next endpoint
        oauth_metadata_request_3 = await auth_flow.asend(oauth_metadata_response_2)
        assert str(oauth_metadata_request_3.url) == "https://auth.example.com/.well-known/openid-configuration/v1/mcp"
        assert oauth_metadata_request_3.method == "GET"

        # Send a 500 response
        oauth_metadata_response_3 = httpx.Response(
            500,
            content=b"Internal Server Error",
            request=oauth_metadata_request_3,
        )

        # Mock the authorization process to minimize unnecessary state in this test
        oauth_provider._perform_authorization = mock.AsyncMock(return_value=("test_auth_code", "test_code_verifier"))

        # Next request should fall back to legacy behavior and auth with the RS (mocked /authorize, next is /token)
        token_request = await auth_flow.asend(oauth_metadata_response_3)
        assert str(token_request.url) == "https://api.example.com/token"
        assert token_request.method == "POST"

        # Send a successful token response
        token_response = httpx.Response(
            200,
            content=(
                b'{"access_token": "new_access_token", "token_type": "Bearer", "expires_in": 3600, '
                b'"refresh_token": "new_refresh_token"}'
            ),
            request=token_request,
        )
        token_request = await auth_flow.asend(token_response)

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

        # Should set metadata
        await oauth_provider._handle_oauth_metadata_response(response)
        assert oauth_provider.context.oauth_metadata is not None
        assert str(oauth_provider.context.oauth_metadata.issuer) == "https://auth.example.com/"

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

    @pytest.mark.anyio
    async def test_auth_flow_with_no_tokens(self, oauth_provider, mock_storage):
        """Test auth flow when no tokens are available, triggering the full OAuth flow."""
        # Ensure no tokens are stored
        oauth_provider.context.current_tokens = None
        oauth_provider.context.token_expiry_time = None
        oauth_provider._initialized = True

        # Create a test request
        test_request = httpx.Request("GET", "https://api.example.com/mcp")

        # Mock the auth flow
        auth_flow = oauth_provider.async_auth_flow(test_request)

        # First request should be the original request without auth header
        request = await auth_flow.__anext__()
        assert "Authorization" not in request.headers

        # Send a 401 response to trigger the OAuth flow
        response = httpx.Response(
            401,
            headers={
                "WWW-Authenticate": 'Bearer resource_metadata="https://api.example.com/.well-known/oauth-protected-resource"'
            },
            request=test_request,
        )

        # Next request should be to discover protected resource metadata
        discovery_request = await auth_flow.asend(response)
        assert discovery_request.method == "GET"
        assert str(discovery_request.url) == "https://api.example.com/.well-known/oauth-protected-resource"

        # Send a successful discovery response with minimal protected resource metadata
        discovery_response = httpx.Response(
            200,
            content=b'{"resource": "https://api.example.com/mcp", "authorization_servers": ["https://auth.example.com"]}',
            request=discovery_request,
        )

        # Next request should be to discover OAuth metadata
        oauth_metadata_request = await auth_flow.asend(discovery_response)
        assert oauth_metadata_request.method == "GET"
        assert str(oauth_metadata_request.url).startswith("https://auth.example.com/")
        assert "mcp-protocol-version" in oauth_metadata_request.headers

        # Send a successful OAuth metadata response
        oauth_metadata_response = httpx.Response(
            200,
            content=(
                b'{"issuer": "https://auth.example.com", '
                b'"authorization_endpoint": "https://auth.example.com/authorize", '
                b'"token_endpoint": "https://auth.example.com/token", '
                b'"registration_endpoint": "https://auth.example.com/register"}'
            ),
            request=oauth_metadata_request,
        )

        # Next request should be to register client
        registration_request = await auth_flow.asend(oauth_metadata_response)
        assert registration_request.method == "POST"
        assert str(registration_request.url) == "https://auth.example.com/register"

        # Send a successful registration response
        registration_response = httpx.Response(
            201,
            content=b'{"client_id": "test_client_id", "client_secret": "test_client_secret", "redirect_uris": ["http://localhost:3030/callback"]}',
            request=registration_request,
        )

        # Mock the authorization process
        oauth_provider._perform_authorization = mock.AsyncMock(return_value=("test_auth_code", "test_code_verifier"))

        # Next request should be to exchange token
        token_request = await auth_flow.asend(registration_response)
        assert token_request.method == "POST"
        assert str(token_request.url) == "https://auth.example.com/token"
        assert "code=test_auth_code" in token_request.content.decode()

        # Send a successful token response
        token_response = httpx.Response(
            200,
            content=(
                b'{"access_token": "new_access_token", "token_type": "Bearer", "expires_in": 3600, '
                b'"refresh_token": "new_refresh_token"}'
            ),
            request=token_request,
        )

        # Final request should be the original request with auth header
        final_request = await auth_flow.asend(token_response)
        assert final_request.headers["Authorization"] == "Bearer new_access_token"
        assert final_request.method == "GET"
        assert str(final_request.url) == "https://api.example.com/mcp"

        # Verify tokens were stored
        assert oauth_provider.context.current_tokens is not None
        assert oauth_provider.context.current_tokens.access_token == "new_access_token"
        assert oauth_provider.context.token_expiry_time is not None


@pytest.mark.parametrize(
    (
        "issuer_url",
        "service_documentation_url",
        "authorization_endpoint",
        "token_endpoint",
        "registration_endpoint",
        "revocation_endpoint",
    ),
    (
        # Pydantic's AnyUrl incorrectly adds trailing slash to base URLs
        # This is being fixed in https://github.com/pydantic/pydantic-core/pull/1719 (Pydantic 2.12+)
        pytest.param(
            "https://auth.example.com",
            "https://auth.example.com/docs",
            "https://auth.example.com/authorize",
            "https://auth.example.com/token",
            "https://auth.example.com/register",
            "https://auth.example.com/revoke",
            id="simple-url",
            marks=pytest.mark.xfail(
                reason="Pydantic AnyUrl adds trailing slash to base URLs - fixed in Pydantic 2.12+"
            ),
        ),
        pytest.param(
            "https://auth.example.com/",
            "https://auth.example.com/docs",
            "https://auth.example.com/authorize",
            "https://auth.example.com/token",
            "https://auth.example.com/register",
            "https://auth.example.com/revoke",
            id="with-trailing-slash",
        ),
        pytest.param(
            "https://auth.example.com/v1/mcp",
            "https://auth.example.com/v1/mcp/docs",
            "https://auth.example.com/v1/mcp/authorize",
            "https://auth.example.com/v1/mcp/token",
            "https://auth.example.com/v1/mcp/register",
            "https://auth.example.com/v1/mcp/revoke",
            id="with-path-param",
        ),
    ),
)
def test_build_metadata(
    issuer_url: str,
    service_documentation_url: str,
    authorization_endpoint: str,
    token_endpoint: str,
    registration_endpoint: str,
    revocation_endpoint: str,
):
    from mcp.server.auth.routes import build_metadata
    from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions

    metadata = build_metadata(
        issuer_url=AnyHttpUrl(issuer_url),
        service_documentation_url=AnyHttpUrl(service_documentation_url),
        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=["read", "write", "admin"]),
        revocation_options=RevocationOptions(enabled=True),
    )

    assert metadata.model_dump(exclude_defaults=True, mode="json") == snapshot(
        {
            "issuer": Is(issuer_url),
            "authorization_endpoint": Is(authorization_endpoint),
            "token_endpoint": Is(token_endpoint),
            "registration_endpoint": Is(registration_endpoint),
            "scopes_supported": ["read", "write", "admin"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["client_secret_post"],
            "service_documentation": Is(service_documentation_url),
            "revocation_endpoint": Is(revocation_endpoint),
            "revocation_endpoint_auth_methods_supported": ["client_secret_post"],
            "code_challenge_methods_supported": ["S256"],
        }
    )


class TestProtectedResourceWWWAuthenticate:
    """Test RFC9728 WWW-Authenticate header parsing functionality for protected resource."""

    @pytest.mark.parametrize(
        "www_auth_header,expected_url",
        [
            # Quoted URL
            (
                'Bearer resource_metadata="https://api.example.com/.well-known/oauth-protected-resource"',
                "https://api.example.com/.well-known/oauth-protected-resource",
            ),
            # Unquoted URL
            (
                "Bearer resource_metadata=https://api.example.com/.well-known/oauth-protected-resource",
                "https://api.example.com/.well-known/oauth-protected-resource",
            ),
            # Complex header with multiple parameters
            (
                'Bearer realm="api", resource_metadata="https://api.example.com/.well-known/oauth-protected-resource", '
                'error="insufficient_scope"',
                "https://api.example.com/.well-known/oauth-protected-resource",
            ),
            # Different URL format
            ('Bearer resource_metadata="https://custom.domain.com/metadata"', "https://custom.domain.com/metadata"),
            # With path and query params
            (
                'Bearer resource_metadata="https://api.example.com/auth/metadata?version=1"',
                "https://api.example.com/auth/metadata?version=1",
            ),
        ],
    )
    def test_extract_resource_metadata_from_www_auth_valid_cases(
        self, client_metadata, mock_storage, www_auth_header, expected_url
    ):
        """Test extraction of resource_metadata URL from various valid WWW-Authenticate headers."""

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

        init_response = httpx.Response(
            status_code=401,
            headers={"WWW-Authenticate": www_auth_header},
            request=httpx.Request("GET", "https://api.example.com/test"),
        )

        result = provider._extract_resource_metadata_from_www_auth(init_response)
        assert result == expected_url

    @pytest.mark.parametrize(
        "status_code,www_auth_header,description",
        [
            # No header
            (401, None, "no WWW-Authenticate header"),
            # Empty header
            (401, "", "empty WWW-Authenticate header"),
            # Header without resource_metadata
            (401, 'Bearer realm="api", error="insufficient_scope"', "no resource_metadata parameter"),
            # Malformed header
            (401, "Bearer resource_metadata=", "malformed resource_metadata parameter"),
            # Non-401 status code
            (
                200,
                'Bearer resource_metadata="https://api.example.com/.well-known/oauth-protected-resource"',
                "200 OK response",
            ),
            (
                500,
                'Bearer resource_metadata="https://api.example.com/.well-known/oauth-protected-resource"',
                "500 error response",
            ),
        ],
    )
    def test_extract_resource_metadata_from_www_auth_invalid_cases(
        self, client_metadata, mock_storage, status_code, www_auth_header, description
    ):
        """Test extraction returns None for invalid cases."""

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

        headers = {"WWW-Authenticate": www_auth_header} if www_auth_header is not None else {}
        init_response = httpx.Response(
            status_code=status_code, headers=headers, request=httpx.Request("GET", "https://api.example.com/test")
        )

        result = provider._extract_resource_metadata_from_www_auth(init_response)
        assert result is None, f"Should return None for {description}"
