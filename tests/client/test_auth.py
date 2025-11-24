"""
Tests for refactored OAuth client authentication implementation.
"""

import base64
import json
import time
from unittest import mock
from urllib.parse import unquote

import httpx
import pytest
from inline_snapshot import Is, snapshot
from pydantic import AnyHttpUrl, AnyUrl

from mcp.client.auth import OAuthClientProvider, OAuthRegistrationError, PKCEParameters
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    create_client_info_from_metadata_url,
    create_client_registration_request,
    create_oauth_metadata_request,
    extract_field_from_www_auth,
    extract_resource_metadata_from_www_auth,
    extract_scope_from_www_auth,
    get_client_metadata_scopes,
    handle_registration_response,
    is_valid_client_metadata_url,
    should_use_client_metadata_url,
)
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)


class MockTokenStorage:
    """Mock token storage for testing."""

    def __init__(self):
        self._tokens: OAuthToken | None = None
        self._client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens  # pragma: no cover

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._client_info  # pragma: no cover

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
def oauth_provider(client_metadata: OAuthClientMetadata, mock_storage: MockTokenStorage):
    async def redirect_handler(url: str) -> None:
        """Mock redirect handler."""
        pass  # pragma: no cover

    async def callback_handler() -> tuple[str, str | None]:
        """Mock callback handler."""
        return "test_auth_code", "test_state"  # pragma: no cover

    return OAuthClientProvider(
        server_url="https://api.example.com/v1/mcp",
        client_metadata=client_metadata,
        storage=mock_storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


@pytest.fixture
def prm_metadata_response():
    """PRM metadata response with scopes."""
    return httpx.Response(
        200,
        content=(
            b'{"resource": "https://api.example.com/v1/mcp", '
            b'"authorization_servers": ["https://auth.example.com"], '
            b'"scopes_supported": ["resource:read", "resource:write"]}'
        ),
    )


@pytest.fixture
def prm_metadata_without_scopes_response():
    """PRM metadata response without scopes."""
    return httpx.Response(
        200,
        content=(
            b'{"resource": "https://api.example.com/v1/mcp", '
            b'"authorization_servers": ["https://auth.example.com"], '
            b'"scopes_supported": null}'
        ),
    )


@pytest.fixture
def init_response_with_www_auth_scope():
    """Initial 401 response with WWW-Authenticate header containing scope."""
    return httpx.Response(
        401,
        headers={"WWW-Authenticate": 'Bearer scope="special:scope from:www-authenticate"'},
        request=httpx.Request("GET", "https://api.example.com/test"),
    )


@pytest.fixture
def init_response_without_www_auth_scope():
    """Initial 401 response without WWW-Authenticate scope."""
    return httpx.Response(
        401,
        headers={},
        request=httpx.Request("GET", "https://api.example.com/test"),
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
    async def test_oauth_provider_initialization(
        self, oauth_provider: OAuthClientProvider, client_metadata: OAuthClientMetadata, mock_storage: MockTokenStorage
    ):
        """Test OAuthClientProvider basic setup."""
        assert oauth_provider.context.server_url == "https://api.example.com/v1/mcp"
        assert oauth_provider.context.client_metadata == client_metadata
        assert oauth_provider.context.storage == mock_storage
        assert oauth_provider.context.timeout == 300.0
        assert oauth_provider.context is not None

    def test_context_url_parsing(self, oauth_provider: OAuthClientProvider):
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
    async def test_token_validity_checking(self, oauth_provider: OAuthClientProvider, valid_tokens: OAuthToken):
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

    def test_clear_tokens(self, oauth_provider: OAuthClientProvider, valid_tokens: OAuthToken):
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
    async def test_build_protected_resource_discovery_urls(
        self, client_metadata: OAuthClientMetadata, mock_storage: MockTokenStorage
    ):
        """Test protected resource metadata discovery URL building with fallback."""

        async def redirect_handler(url: str) -> None:
            pass  # pragma: no cover

        async def callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "test_state"  # pragma: no cover

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

        urls = build_protected_resource_metadata_discovery_urls(
            extract_resource_metadata_from_www_auth(init_response), provider.context.server_url
        )
        assert len(urls) == 1
        assert urls[0] == "https://api.example.com/.well-known/oauth-protected-resource"

        # Test with WWW-Authenticate header
        init_response.headers["WWW-Authenticate"] = (
            'Bearer resource_metadata="https://prm.example.com/.well-known/oauth-protected-resource/path"'
        )

        urls = build_protected_resource_metadata_discovery_urls(
            extract_resource_metadata_from_www_auth(init_response), provider.context.server_url
        )
        assert len(urls) == 2
        assert urls[0] == "https://prm.example.com/.well-known/oauth-protected-resource/path"
        assert urls[1] == "https://api.example.com/.well-known/oauth-protected-resource"

    @pytest.mark.anyio
    def test_create_oauth_metadata_request(self, oauth_provider: OAuthClientProvider):
        """Test OAuth metadata discovery request building."""
        request = create_oauth_metadata_request("https://example.com")

        # Ensure correct method and headers, and that the URL is unmodified
        assert request.method == "GET"
        assert str(request.url) == "https://example.com"
        assert "mcp-protocol-version" in request.headers


class TestOAuthFallback:
    """Test OAuth discovery fallback behavior for legacy (act as AS not RS) servers."""

    @pytest.mark.anyio
    async def test_oauth_discovery_legacy_fallback_when_no_prm(self):
        """Test that when PRM discovery fails, only root OAuth URL is tried (March 2025 spec)."""
        # When auth_server_url is None (PRM failed), we use server_url and only try root
        discovery_urls = build_oauth_authorization_server_metadata_discovery_urls(None, "https://mcp.linear.app/sse")

        # Should only try the root URL (legacy behavior)
        assert discovery_urls == [
            "https://mcp.linear.app/.well-known/oauth-authorization-server",
        ]

    @pytest.mark.anyio
    async def test_oauth_discovery_path_aware_when_auth_server_has_path(self):
        """Test that when auth server URL has a path, only path-based URLs are tried."""
        discovery_urls = build_oauth_authorization_server_metadata_discovery_urls(
            "https://auth.example.com/tenant1", "https://api.example.com/mcp"
        )

        # Should try path-based URLs only (no root URLs)
        assert discovery_urls == [
            "https://auth.example.com/.well-known/oauth-authorization-server/tenant1",
            "https://auth.example.com/.well-known/openid-configuration/tenant1",
            "https://auth.example.com/tenant1/.well-known/openid-configuration",
        ]

    @pytest.mark.anyio
    async def test_oauth_discovery_root_when_auth_server_has_no_path(self):
        """Test that when auth server URL has no path, only root URLs are tried."""
        discovery_urls = build_oauth_authorization_server_metadata_discovery_urls(
            "https://auth.example.com", "https://api.example.com/mcp"
        )

        # Should try root URLs only
        assert discovery_urls == [
            "https://auth.example.com/.well-known/oauth-authorization-server",
            "https://auth.example.com/.well-known/openid-configuration",
        ]

    @pytest.mark.anyio
    async def test_oauth_discovery_root_when_auth_server_has_only_slash(self):
        """Test that when auth server URL has only trailing slash, treated as root."""
        discovery_urls = build_oauth_authorization_server_metadata_discovery_urls(
            "https://auth.example.com/", "https://api.example.com/mcp"
        )

        # Should try root URLs only
        assert discovery_urls == [
            "https://auth.example.com/.well-known/oauth-authorization-server",
            "https://auth.example.com/.well-known/openid-configuration",
        ]

    @pytest.mark.anyio
    async def test_oauth_discovery_fallback_order(self, oauth_provider: OAuthClientProvider):
        """Test fallback URL construction order when auth server URL has a path."""
        # Simulate PRM discovery returning an auth server URL with a path
        oauth_provider.context.auth_server_url = oauth_provider.context.server_url

        discovery_urls = build_oauth_authorization_server_metadata_discovery_urls(
            oauth_provider.context.auth_server_url, oauth_provider.context.server_url
        )

        assert discovery_urls == [
            "https://api.example.com/.well-known/oauth-authorization-server/v1/mcp",
            "https://api.example.com/.well-known/openid-configuration/v1/mcp",
            "https://api.example.com/v1/mcp/.well-known/openid-configuration",
        ]

    @pytest.mark.anyio
    async def test_oauth_discovery_fallback_conditions(self, oauth_provider: OAuthClientProvider):
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
        # Note: auth server URL has a path (/v1/mcp), so only path-based URLs will be tried
        discovery_response = httpx.Response(
            200,
            content=b'{"resource": "https://api.example.com/v1/mcp", "authorization_servers": ["https://auth.example.com/v1/mcp"]}',
            request=discovery_request,
        )

        # Next request should be to discover OAuth metadata at path-aware OAuth URL
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

        # Next request should be path-aware OIDC URL (not root URL since auth server has path)
        oauth_metadata_request_2 = await auth_flow.asend(oauth_metadata_response_1)
        assert str(oauth_metadata_request_2.url) == "https://auth.example.com/.well-known/openid-configuration/v1/mcp"
        assert oauth_metadata_request_2.method == "GET"

        # Send a 400 response
        oauth_metadata_response_2 = httpx.Response(
            400,
            content=b"Bad Request",
            request=oauth_metadata_request_2,
        )

        # Next request should be OIDC path-appended URL
        oauth_metadata_request_3 = await auth_flow.asend(oauth_metadata_response_2)
        assert str(oauth_metadata_request_3.url) == "https://auth.example.com/v1/mcp/.well-known/openid-configuration"
        assert oauth_metadata_request_3.method == "GET"

        # Send a 500 response
        oauth_metadata_response_3 = httpx.Response(
            500,
            content=b"Internal Server Error",
            request=oauth_metadata_request_3,
        )

        # Mock the authorization process to minimize unnecessary state in this test
        oauth_provider._perform_authorization_code_grant = mock.AsyncMock(
            return_value=("test_auth_code", "test_code_verifier")
        )

        # All path-based URLs failed, flow continues with default endpoints
        # Next request should be token exchange using MCP server base URL (fallback when OAuth metadata not found)
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

        # After OAuth flow completes, the original request is retried with auth header
        final_request = await auth_flow.asend(token_response)
        assert final_request.headers["Authorization"] == "Bearer new_access_token"
        assert final_request.method == "GET"
        assert str(final_request.url) == "https://api.example.com/v1/mcp"

        # Send final success response to properly close the generator
        final_response = httpx.Response(200, request=final_request)
        try:
            await auth_flow.asend(final_response)
        except StopAsyncIteration:
            pass  # Expected - generator should complete

    @pytest.mark.anyio
    async def test_handle_metadata_response_success(self, oauth_provider: OAuthClientProvider):
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
    async def test_prioritize_www_auth_scope_over_prm(
        self,
        oauth_provider: OAuthClientProvider,
        prm_metadata_response: httpx.Response,
        init_response_with_www_auth_scope: httpx.Response,
    ):
        """Test that WWW-Authenticate scope is prioritized over PRM scopes."""
        # First, process PRM metadata to set protected_resource_metadata with scopes
        await oauth_provider._handle_protected_resource_response(prm_metadata_response)

        # Process the scope selection with WWW-Authenticate header
        scopes = get_client_metadata_scopes(
            extract_scope_from_www_auth(init_response_with_www_auth_scope),
            oauth_provider.context.protected_resource_metadata,
        )

        # Verify that WWW-Authenticate scope is used (not PRM scopes)
        assert scopes == "special:scope from:www-authenticate"

    @pytest.mark.anyio
    async def test_prioritize_prm_scopes_when_no_www_auth_scope(
        self,
        oauth_provider: OAuthClientProvider,
        prm_metadata_response: httpx.Response,
        init_response_without_www_auth_scope: httpx.Response,
    ):
        """Test that PRM scopes are prioritized when WWW-Authenticate header has no scopes."""
        # Process the PRM metadata to set protected_resource_metadata with scopes
        await oauth_provider._handle_protected_resource_response(prm_metadata_response)

        # Process the scope selection without WWW-Authenticate scope
        scopes = get_client_metadata_scopes(
            extract_scope_from_www_auth(init_response_without_www_auth_scope),
            oauth_provider.context.protected_resource_metadata,
        )

        # Verify that PRM scopes are used
        assert scopes == "resource:read resource:write"

    @pytest.mark.anyio
    async def test_omit_scope_when_no_prm_scopes_or_www_auth(
        self,
        oauth_provider: OAuthClientProvider,
        prm_metadata_without_scopes_response: httpx.Response,
        init_response_without_www_auth_scope: httpx.Response,
    ):
        """Test that scope is omitted when PRM has no scopes and WWW-Authenticate doesn't specify scope."""
        # Process the PRM metadata without scopes
        await oauth_provider._handle_protected_resource_response(prm_metadata_without_scopes_response)

        # Process the scope selection without WWW-Authenticate scope
        scopes = get_client_metadata_scopes(
            extract_scope_from_www_auth(init_response_without_www_auth_scope),
            oauth_provider.context.protected_resource_metadata,
        )
        # Verify that scope is omitted
        assert scopes is None

    @pytest.mark.anyio
    async def test_register_client_request(self, oauth_provider: OAuthClientProvider):
        """Test client registration request building."""
        request = await oauth_provider._register_client()

        assert request is not None
        assert request.method == "POST"
        assert str(request.url) == "https://api.example.com/register"
        assert request.headers["Content-Type"] == "application/json"

    @pytest.mark.anyio
    async def test_register_client_skip_if_registered(self, oauth_provider: OAuthClientProvider):
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
    async def test_register_client_explicit_auth_method(self, mock_storage: MockTokenStorage):
        """Test that explicitly set token_endpoint_auth_method is used without auto-selection."""

        async def redirect_handler(url: str) -> None:
            pass  # pragma: no cover

        async def callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "test_state"  # pragma: no cover

        # Create client metadata with explicit auth method
        explicit_metadata = OAuthClientMetadata(
            client_name="Test Client",
            client_uri=AnyHttpUrl("https://example.com"),
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
            scope="read write",
            token_endpoint_auth_method="client_secret_basic",
        )
        provider = OAuthClientProvider(
            server_url="https://api.example.com/v1/mcp",
            client_metadata=explicit_metadata,
            storage=mock_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

        request = await provider._register_client()
        assert request is not None

        body = json.loads(request.content)
        # Should use the explicitly set method, not auto-select
        assert body["token_endpoint_auth_method"] == "client_secret_basic"

    @pytest.mark.anyio
    async def test_register_client_none_auth_method_with_server_metadata(self, oauth_provider: OAuthClientProvider):
        """Test that token_endpoint_auth_method=None selects from server's supported methods."""
        # Set server metadata with specific supported methods
        oauth_provider.context.oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://auth.example.com"),
            authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
            token_endpoint_auth_methods_supported=["client_secret_post"],
        )
        # Ensure client_metadata has None for token_endpoint_auth_method

        request = await oauth_provider._register_client()
        assert request is not None

        body = json.loads(request.content)
        assert body["token_endpoint_auth_method"] == "client_secret_post"

    @pytest.mark.anyio
    async def test_register_client_none_auth_method_no_compatible(self, oauth_provider: OAuthClientProvider):
        """Test that registration raises error when no compatible auth methods."""
        # Set server metadata with unsupported methods only
        oauth_provider.context.oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://auth.example.com"),
            authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
            token_endpoint_auth_methods_supported=["private_key_jwt", "client_secret_jwt"],
        )

        with pytest.raises(OAuthRegistrationError) as exc_info:
            await oauth_provider._register_client()

        assert "No compatible authentication methods" in str(exc_info.value)
        assert "private_key_jwt" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_token_exchange_request_authorization_code(self, oauth_provider: OAuthClientProvider):
        """Test token exchange request building."""
        # Set up required context
        oauth_provider.context.client_info = OAuthClientInformationFull(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
            token_endpoint_auth_method="client_secret_post",
        )

        request = await oauth_provider._exchange_token_authorization_code("test_auth_code", "test_verifier")

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
    async def test_refresh_token_request(self, oauth_provider: OAuthClientProvider, valid_tokens: OAuthToken):
        """Test refresh token request building."""
        # Set up required context
        oauth_provider.context.current_tokens = valid_tokens
        oauth_provider.context.client_info = OAuthClientInformationFull(
            client_id="test_client",
            client_secret="test_secret",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
            token_endpoint_auth_method="client_secret_post",
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

    @pytest.mark.anyio
    async def test_basic_auth_token_exchange(self, oauth_provider: OAuthClientProvider):
        """Test token exchange with client_secret_basic authentication."""
        # Set up OAuth metadata to support basic auth
        oauth_provider.context.oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://auth.example.com"),
            authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
            token_endpoint_auth_methods_supported=["client_secret_basic", "client_secret_post"],
        )

        client_id_raw = "test@client"  # Include special character to test URL encoding
        client_secret_raw = "test:secret"  # Include colon to test URL encoding

        oauth_provider.context.client_info = OAuthClientInformationFull(
            client_id=client_id_raw,
            client_secret=client_secret_raw,
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
            token_endpoint_auth_method="client_secret_basic",
        )

        request = await oauth_provider._exchange_token_authorization_code("test_auth_code", "test_verifier")

        # Should use basic auth (registered method)
        assert "Authorization" in request.headers
        assert request.headers["Authorization"].startswith("Basic ")

        # Decode and verify credentials are properly URL-encoded
        encoded_creds = request.headers["Authorization"][6:]  # Remove "Basic " prefix
        decoded = base64.b64decode(encoded_creds).decode()
        client_id, client_secret = decoded.split(":", 1)

        # Check URL encoding was applied
        assert client_id == "test%40client"  # @ should be encoded as %40
        assert client_secret == "test%3Asecret"  # : should be encoded as %3A

        # Verify decoded values match original
        assert unquote(client_id) == client_id_raw
        assert unquote(client_secret) == client_secret_raw

        # client_secret should NOT be in body for basic auth
        content = request.content.decode()
        assert "client_secret=" not in content
        assert "client_id=test%40client" in content  # client_id still in body

    @pytest.mark.anyio
    async def test_basic_auth_refresh_token(self, oauth_provider: OAuthClientProvider, valid_tokens: OAuthToken):
        """Test token refresh with client_secret_basic authentication."""
        oauth_provider.context.current_tokens = valid_tokens

        # Set up OAuth metadata to only support basic auth
        oauth_provider.context.oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://auth.example.com"),
            authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
            token_endpoint_auth_methods_supported=["client_secret_basic"],
        )

        client_id = "test_client"
        client_secret = "test_secret"
        oauth_provider.context.client_info = OAuthClientInformationFull(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
            token_endpoint_auth_method="client_secret_basic",
        )

        request = await oauth_provider._refresh_token()

        assert "Authorization" in request.headers
        assert request.headers["Authorization"].startswith("Basic ")

        encoded_creds = request.headers["Authorization"][6:]
        decoded = base64.b64decode(encoded_creds).decode()
        assert decoded == f"{client_id}:{client_secret}"

        # client_secret should NOT be in body
        content = request.content.decode()
        assert "client_secret=" not in content

    @pytest.mark.anyio
    async def test_none_auth_method(self, oauth_provider: OAuthClientProvider):
        """Test 'none' authentication method (public client)."""
        oauth_provider.context.oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://auth.example.com"),
            authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
            token_endpoint_auth_methods_supported=["none"],
        )

        client_id = "public_client"
        oauth_provider.context.client_info = OAuthClientInformationFull(
            client_id=client_id,
            client_secret=None,  # No secret for public client
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
            token_endpoint_auth_method="none",
        )

        request = await oauth_provider._exchange_token_authorization_code("test_auth_code", "test_verifier")

        # Should NOT have Authorization header
        assert "Authorization" not in request.headers

        # Should NOT have client_secret in body
        content = request.content.decode()
        assert "client_secret=" not in content
        assert "client_id=public_client" in content


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
        request = await oauth_provider._exchange_token_authorization_code("test_code", "test_verifier")
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
        request = await oauth_provider._exchange_token_authorization_code("test_code", "test_verifier")
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
        request = await oauth_provider._exchange_token_authorization_code("test_code", "test_verifier")
        content = request.content.decode()
        assert "resource=" in content


class TestRegistrationResponse:
    """Test client registration response handling."""

    @pytest.mark.anyio
    async def test_handle_registration_response_reads_before_accessing_text(self):
        """Test that response.aread() is called before accessing response.text."""

        # Track if aread() was called
        class MockResponse(httpx.Response):
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
                    raise RuntimeError("Response.text accessed before response.aread()")  # pragma: no cover
                return self._text

        mock_response = MockResponse()

        # This should call aread() before accessing text
        with pytest.raises(Exception) as exc_info:
            await handle_registration_response(mock_response)

        # Verify aread() was called
        assert mock_response._aread_called
        # Verify the error message includes the response text
        assert "Registration failed: 400" in str(exc_info.value)


class TestCreateClientRegistrationRequest:
    """Test client registration request creation."""

    def test_uses_registration_endpoint_from_metadata(self):
        """Test that registration URL comes from metadata when available."""
        oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://auth.example.com"),
            authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
            registration_endpoint=AnyHttpUrl("https://auth.example.com/register"),
        )
        client_metadata = OAuthClientMetadata(redirect_uris=[AnyHttpUrl("http://localhost:3000/callback")])

        request = create_client_registration_request(oauth_metadata, client_metadata, "https://auth.example.com")

        assert str(request.url) == "https://auth.example.com/register"
        assert request.method == "POST"

    def test_falls_back_to_default_register_endpoint_when_no_metadata(self):
        """Test that registration uses fallback URL when auth_server_metadata is None."""
        client_metadata = OAuthClientMetadata(redirect_uris=[AnyHttpUrl("http://localhost:3000/callback")])

        request = create_client_registration_request(None, client_metadata, "https://auth.example.com")

        assert str(request.url) == "https://auth.example.com/register"
        assert request.method == "POST"

    def test_falls_back_when_metadata_has_no_registration_endpoint(self):
        """Test fallback when metadata exists but lacks registration_endpoint."""
        oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://auth.example.com"),
            authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
            # No registration_endpoint
        )
        client_metadata = OAuthClientMetadata(redirect_uris=[AnyHttpUrl("http://localhost:3000/callback")])

        request = create_client_registration_request(oauth_metadata, client_metadata, "https://auth.example.com")

        assert str(request.url) == "https://auth.example.com/register"
        assert request.method == "POST"


class TestAuthFlow:
    """Test the auth flow in httpx."""

    @pytest.mark.anyio
    async def test_auth_flow_with_valid_tokens(
        self, oauth_provider: OAuthClientProvider, mock_storage: MockTokenStorage, valid_tokens: OAuthToken
    ):
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
    async def test_auth_flow_with_no_tokens(self, oauth_provider: OAuthClientProvider, mock_storage: MockTokenStorage):
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
        oauth_provider._perform_authorization_code_grant = mock.AsyncMock(
            return_value=("test_auth_code", "test_code_verifier")
        )

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

        # Send final success response to properly close the generator
        final_response = httpx.Response(200, request=final_request)
        try:
            await auth_flow.asend(final_response)
        except StopAsyncIteration:
            pass  # Expected - generator should complete

        # Verify tokens were stored
        assert oauth_provider.context.current_tokens is not None
        assert oauth_provider.context.current_tokens.access_token == "new_access_token"
        assert oauth_provider.context.token_expiry_time is not None

    @pytest.mark.anyio
    async def test_auth_flow_no_unnecessary_retry_after_oauth(
        self, oauth_provider: OAuthClientProvider, mock_storage: MockTokenStorage, valid_tokens: OAuthToken
    ):
        """Test that requests are not retried unnecessarily - the core bug that caused 2x performance degradation."""
        # Pre-store valid tokens so no OAuth flow is needed
        await mock_storage.set_tokens(valid_tokens)
        oauth_provider.context.current_tokens = valid_tokens
        oauth_provider.context.token_expiry_time = time.time() + 1800
        oauth_provider._initialized = True

        test_request = httpx.Request("GET", "https://api.example.com/mcp")
        auth_flow = oauth_provider.async_auth_flow(test_request)

        # Count how many times the request is yielded
        request_yields = 0

        # First request - should have auth header already
        request = await auth_flow.__anext__()
        request_yields += 1
        assert request.headers["Authorization"] == "Bearer test_access_token"

        # Send a successful 200 response
        response = httpx.Response(200, request=request)

        # In the buggy version, this would yield the request AGAIN unconditionally
        # In the fixed version, this should end the generator
        try:
            await auth_flow.asend(response)  # extra request
            request_yields += 1  # pragma: no cover
            # If we reach here, the bug is present
            pytest.fail(
                f"Unnecessary retry detected! Request was yielded {request_yields} times. "
                f"This indicates the retry logic bug that caused 2x performance degradation. "
                f"The request should only be yielded once for successful responses."
            )  # pragma: no cover
        except StopAsyncIteration:
            # This is the expected behavior - no unnecessary retry
            pass

        # Verify exactly one request was yielded (no double-sending)
        assert request_yields == 1, f"Expected 1 request yield, got {request_yields}"

    @pytest.mark.anyio
    async def test_403_insufficient_scope_updates_scope_from_header(
        self,
        oauth_provider: OAuthClientProvider,
        mock_storage: MockTokenStorage,
        valid_tokens: OAuthToken,
    ):
        """Test that 403 response correctly updates scope from WWW-Authenticate header."""
        # Pre-store valid tokens and client info
        client_info = OAuthClientInformationFull(
            client_id="test_client_id",
            client_secret="test_client_secret",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        )
        await mock_storage.set_tokens(valid_tokens)
        await mock_storage.set_client_info(client_info)
        oauth_provider.context.current_tokens = valid_tokens
        oauth_provider.context.token_expiry_time = time.time() + 1800
        oauth_provider.context.client_info = client_info
        oauth_provider._initialized = True

        # Original scope
        assert oauth_provider.context.client_metadata.scope == "read write"

        redirect_captured = False
        captured_state = None

        async def capture_redirect(url: str) -> None:
            nonlocal redirect_captured, captured_state
            redirect_captured = True
            # Verify the new scope is included in authorization URL
            assert "scope=admin%3Awrite+admin%3Adelete" in url or "scope=admin:write+admin:delete" in url.replace(
                "%3A", ":"
            ).replace("+", " ")
            # Extract state from redirect URL
            from urllib.parse import parse_qs, urlparse

            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            captured_state = params.get("state", [None])[0]

        oauth_provider.context.redirect_handler = capture_redirect

        # Mock callback
        async def mock_callback() -> tuple[str, str | None]:
            return "auth_code", captured_state

        oauth_provider.context.callback_handler = mock_callback

        test_request = httpx.Request("GET", "https://api.example.com/mcp")
        auth_flow = oauth_provider.async_auth_flow(test_request)

        # First request
        request = await auth_flow.__anext__()

        # Send 403 with new scope requirement
        response_403 = httpx.Response(
            403,
            headers={"WWW-Authenticate": 'Bearer error="insufficient_scope", scope="admin:write admin:delete"'},
            request=request,
        )

        # Trigger step-up - should get token exchange request
        token_exchange_request = await auth_flow.asend(response_403)

        # Verify scope was updated
        assert oauth_provider.context.client_metadata.scope == "admin:write admin:delete"
        assert redirect_captured

        # Complete the flow with successful token response
        token_response = httpx.Response(
            200,
            json={
                "access_token": "new_token_with_new_scope",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "admin:write admin:delete",
            },
            request=token_exchange_request,
        )

        # Should get final retry request
        final_request = await auth_flow.asend(token_response)

        # Send success response - flow should complete
        success_response = httpx.Response(200, request=final_request)
        try:
            await auth_flow.asend(success_response)
            pytest.fail("Should have stopped after successful response")  # pragma: no cover
        except StopAsyncIteration:
            pass  # Expected


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
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
            "service_documentation": Is(service_documentation_url),
            "revocation_endpoint": Is(revocation_endpoint),
            "revocation_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
            "code_challenge_methods_supported": ["S256"],
        }
    )


class TestLegacyServerFallback:
    """Test backward compatibility with legacy servers that don't support PRM (issue #1495)."""

    @pytest.mark.anyio
    async def test_legacy_server_no_prm_falls_back_to_root_oauth_discovery(
        self, client_metadata: OAuthClientMetadata, mock_storage: MockTokenStorage
    ):
        """Test that when PRM discovery fails completely, we fall back to root OAuth discovery (March 2025 spec)."""

        async def redirect_handler(url: str) -> None:
            pass  # pragma: no cover

        async def callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "test_state"  # pragma: no cover

        # Simulate a legacy server like Linear
        provider = OAuthClientProvider(
            server_url="https://mcp.linear.app/sse",
            client_metadata=client_metadata,
            storage=mock_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

        provider.context.current_tokens = None
        provider.context.token_expiry_time = None
        provider._initialized = True

        # Mock client info to skip DCR
        provider.context.client_info = OAuthClientInformationFull(
            client_id="existing_client",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        )

        test_request = httpx.Request("GET", "https://mcp.linear.app/sse")
        auth_flow = provider.async_auth_flow(test_request)

        # First request
        request = await auth_flow.__anext__()
        assert "Authorization" not in request.headers

        # Send 401 without WWW-Authenticate header (typical legacy server)
        response = httpx.Response(401, headers={}, request=test_request)

        # Should try path-based PRM first
        prm_request_1 = await auth_flow.asend(response)
        assert str(prm_request_1.url) == "https://mcp.linear.app/.well-known/oauth-protected-resource/sse"

        # PRM returns 404
        prm_response_1 = httpx.Response(404, request=prm_request_1)

        # Should try root-based PRM
        prm_request_2 = await auth_flow.asend(prm_response_1)
        assert str(prm_request_2.url) == "https://mcp.linear.app/.well-known/oauth-protected-resource"

        # PRM returns 404 again - all PRM URLs failed
        prm_response_2 = httpx.Response(404, request=prm_request_2)

        # Should fall back to root OAuth discovery (March 2025 spec behavior)
        oauth_metadata_request = await auth_flow.asend(prm_response_2)
        assert str(oauth_metadata_request.url) == "https://mcp.linear.app/.well-known/oauth-authorization-server"
        assert oauth_metadata_request.method == "GET"

        # Send successful OAuth metadata response
        oauth_metadata_response = httpx.Response(
            200,
            content=(
                b'{"issuer": "https://mcp.linear.app", '
                b'"authorization_endpoint": "https://mcp.linear.app/authorize", '
                b'"token_endpoint": "https://mcp.linear.app/token"}'
            ),
            request=oauth_metadata_request,
        )

        # Mock authorization
        provider._perform_authorization_code_grant = mock.AsyncMock(
            return_value=("test_auth_code", "test_code_verifier")
        )

        # Next should be token exchange
        token_request = await auth_flow.asend(oauth_metadata_response)
        assert str(token_request.url) == "https://mcp.linear.app/token"

        # Send successful token response
        token_response = httpx.Response(
            200,
            content=b'{"access_token": "linear_token", "token_type": "Bearer", "expires_in": 3600}',
            request=token_request,
        )

        # Final request with auth header
        final_request = await auth_flow.asend(token_response)
        assert final_request.headers["Authorization"] == "Bearer linear_token"
        assert str(final_request.url) == "https://mcp.linear.app/sse"

        # Complete flow
        final_response = httpx.Response(200, request=final_request)
        try:
            await auth_flow.asend(final_response)
        except StopAsyncIteration:
            pass

    @pytest.mark.anyio
    async def test_legacy_server_with_different_prm_and_root_urls(
        self, client_metadata: OAuthClientMetadata, mock_storage: MockTokenStorage
    ):
        """Test PRM fallback with different WWW-Authenticate and root URLs."""

        async def redirect_handler(url: str) -> None:
            pass  # pragma: no cover

        async def callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "test_state"  # pragma: no cover

        provider = OAuthClientProvider(
            server_url="https://api.example.com/v1/mcp",
            client_metadata=client_metadata,
            storage=mock_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

        provider.context.current_tokens = None
        provider.context.token_expiry_time = None
        provider._initialized = True

        provider.context.client_info = OAuthClientInformationFull(
            client_id="existing_client",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        )

        test_request = httpx.Request("GET", "https://api.example.com/v1/mcp")
        auth_flow = provider.async_auth_flow(test_request)

        await auth_flow.__anext__()

        # 401 with custom WWW-Authenticate PRM URL
        response = httpx.Response(
            401,
            headers={
                "WWW-Authenticate": 'Bearer resource_metadata="https://custom.prm.com/.well-known/oauth-protected-resource"'
            },
            request=test_request,
        )

        # Try custom PRM URL first
        prm_request_1 = await auth_flow.asend(response)
        assert str(prm_request_1.url) == "https://custom.prm.com/.well-known/oauth-protected-resource"

        # Returns 500
        prm_response_1 = httpx.Response(500, request=prm_request_1)

        # Try path-based fallback
        prm_request_2 = await auth_flow.asend(prm_response_1)
        assert str(prm_request_2.url) == "https://api.example.com/.well-known/oauth-protected-resource/v1/mcp"

        # Returns 404
        prm_response_2 = httpx.Response(404, request=prm_request_2)

        # Try root fallback
        prm_request_3 = await auth_flow.asend(prm_response_2)
        assert str(prm_request_3.url) == "https://api.example.com/.well-known/oauth-protected-resource"

        # Also returns 404 - all PRM URLs failed
        prm_response_3 = httpx.Response(404, request=prm_request_3)

        # Should fall back to root OAuth discovery
        oauth_metadata_request = await auth_flow.asend(prm_response_3)
        assert str(oauth_metadata_request.url) == "https://api.example.com/.well-known/oauth-authorization-server"

        # Complete the flow
        oauth_metadata_response = httpx.Response(
            200,
            content=(
                b'{"issuer": "https://api.example.com", '
                b'"authorization_endpoint": "https://api.example.com/authorize", '
                b'"token_endpoint": "https://api.example.com/token"}'
            ),
            request=oauth_metadata_request,
        )

        provider._perform_authorization_code_grant = mock.AsyncMock(
            return_value=("test_auth_code", "test_code_verifier")
        )

        token_request = await auth_flow.asend(oauth_metadata_response)
        assert str(token_request.url) == "https://api.example.com/token"

        token_response = httpx.Response(
            200,
            content=b'{"access_token": "test_token", "token_type": "Bearer", "expires_in": 3600}',
            request=token_request,
        )

        final_request = await auth_flow.asend(token_response)
        assert final_request.headers["Authorization"] == "Bearer test_token"

        final_response = httpx.Response(200, request=final_request)
        try:
            await auth_flow.asend(final_response)
        except StopAsyncIteration:
            pass


class TestSEP985Discovery:
    """Test SEP-985 protected resource metadata discovery with fallback."""

    @pytest.mark.anyio
    async def test_path_based_fallback_when_no_www_authenticate(
        self, client_metadata: OAuthClientMetadata, mock_storage: MockTokenStorage
    ):
        """Test that client falls back to path-based well-known URI when WWW-Authenticate is absent."""

        async def redirect_handler(url: str) -> None:
            pass  # pragma: no cover

        async def callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "test_state"  # pragma: no cover

        provider = OAuthClientProvider(
            server_url="https://api.example.com/v1/mcp",
            client_metadata=client_metadata,
            storage=mock_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

        # Test with 401 response without WWW-Authenticate header
        init_response = httpx.Response(
            status_code=401, headers={}, request=httpx.Request("GET", "https://api.example.com/v1/mcp")
        )

        # Build discovery URLs
        discovery_urls = build_protected_resource_metadata_discovery_urls(
            extract_resource_metadata_from_www_auth(init_response), provider.context.server_url
        )

        # Should have path-based URL first, then root-based URL
        assert len(discovery_urls) == 2
        assert discovery_urls[0] == "https://api.example.com/.well-known/oauth-protected-resource/v1/mcp"
        assert discovery_urls[1] == "https://api.example.com/.well-known/oauth-protected-resource"

    @pytest.mark.anyio
    async def test_root_based_fallback_after_path_based_404(
        self, client_metadata: OAuthClientMetadata, mock_storage: MockTokenStorage
    ):
        """Test that client falls back to root-based URI when path-based returns 404."""

        async def redirect_handler(url: str) -> None:
            pass  # pragma: no cover

        async def callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "test_state"  # pragma: no cover

        provider = OAuthClientProvider(
            server_url="https://api.example.com/v1/mcp",
            client_metadata=client_metadata,
            storage=mock_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

        # Ensure no tokens are stored
        provider.context.current_tokens = None
        provider.context.token_expiry_time = None
        provider._initialized = True

        # Mock client info to skip DCR
        provider.context.client_info = OAuthClientInformationFull(
            client_id="existing_client",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        )

        # Create a test request
        test_request = httpx.Request("GET", "https://api.example.com/v1/mcp")

        # Mock the auth flow
        auth_flow = provider.async_auth_flow(test_request)

        # First request should be the original request without auth header
        request = await auth_flow.__anext__()
        assert "Authorization" not in request.headers

        # Send a 401 response without WWW-Authenticate header
        response = httpx.Response(401, headers={}, request=test_request)

        # Next request should be to discover protected resource metadata (path-based)
        discovery_request_1 = await auth_flow.asend(response)
        assert str(discovery_request_1.url) == "https://api.example.com/.well-known/oauth-protected-resource/v1/mcp"
        assert discovery_request_1.method == "GET"

        # Send 404 response for path-based discovery
        discovery_response_1 = httpx.Response(404, request=discovery_request_1)

        # Next request should be to root-based well-known URI
        discovery_request_2 = await auth_flow.asend(discovery_response_1)
        assert str(discovery_request_2.url) == "https://api.example.com/.well-known/oauth-protected-resource"
        assert discovery_request_2.method == "GET"

        # Send successful discovery response
        discovery_response_2 = httpx.Response(
            200,
            content=(
                b'{"resource": "https://api.example.com/v1/mcp", "authorization_servers": ["https://auth.example.com"]}'
            ),
            request=discovery_request_2,
        )

        # Mock the rest of the OAuth flow
        provider._perform_authorization = mock.AsyncMock(return_value=("test_auth_code", "test_code_verifier"))

        # Next should be OAuth metadata discovery
        oauth_metadata_request = await auth_flow.asend(discovery_response_2)
        assert oauth_metadata_request.method == "GET"

        # Complete the flow
        oauth_metadata_response = httpx.Response(
            200,
            content=(
                b'{"issuer": "https://auth.example.com", '
                b'"authorization_endpoint": "https://auth.example.com/authorize", '
                b'"token_endpoint": "https://auth.example.com/token"}'
            ),
            request=oauth_metadata_request,
        )

        token_request = await auth_flow.asend(oauth_metadata_response)
        token_response = httpx.Response(
            200,
            content=(
                b'{"access_token": "new_access_token", "token_type": "Bearer", "expires_in": 3600, '
                b'"refresh_token": "new_refresh_token"}'
            ),
            request=token_request,
        )

        final_request = await auth_flow.asend(token_response)
        final_response = httpx.Response(200, request=final_request)
        try:
            await auth_flow.asend(final_response)
        except StopAsyncIteration:  # pragma: no cover
            pass

    @pytest.mark.anyio
    async def test_www_authenticate_takes_priority_over_well_known(
        self, client_metadata: OAuthClientMetadata, mock_storage: MockTokenStorage
    ):
        """Test that WWW-Authenticate header resource_metadata takes priority over well-known URIs."""

        async def redirect_handler(url: str) -> None:
            pass  # pragma: no cover

        async def callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "test_state"  # pragma: no cover

        provider = OAuthClientProvider(
            server_url="https://api.example.com/v1/mcp",
            client_metadata=client_metadata,
            storage=mock_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

        # Test with 401 response with WWW-Authenticate header
        init_response = httpx.Response(
            status_code=401,
            headers={
                "WWW-Authenticate": 'Bearer resource_metadata="https://custom.example.com/.well-known/oauth-protected-resource"'
            },
            request=httpx.Request("GET", "https://api.example.com/v1/mcp"),
        )

        # Build discovery URLs
        discovery_urls = build_protected_resource_metadata_discovery_urls(
            extract_resource_metadata_from_www_auth(init_response), provider.context.server_url
        )

        # Should have WWW-Authenticate URL first, then fallback URLs
        assert len(discovery_urls) == 3
        assert discovery_urls[0] == "https://custom.example.com/.well-known/oauth-protected-resource"
        assert discovery_urls[1] == "https://api.example.com/.well-known/oauth-protected-resource/v1/mcp"
        assert discovery_urls[2] == "https://api.example.com/.well-known/oauth-protected-resource"


class TestWWWAuthenticate:
    """Test WWW-Authenticate header parsing functionality."""

    @pytest.mark.parametrize(
        "www_auth_header,field_name,expected_value",
        [
            # Quoted values
            ('Bearer scope="read write"', "scope", "read write"),
            (
                'Bearer resource_metadata="https://api.example.com/.well-known/oauth-protected-resource"',
                "resource_metadata",
                "https://api.example.com/.well-known/oauth-protected-resource",
            ),
            ('Bearer error="insufficient_scope"', "error", "insufficient_scope"),
            # Unquoted values
            ("Bearer scope=read", "scope", "read"),
            (
                "Bearer resource_metadata=https://api.example.com/.well-known/oauth-protected-resource",
                "resource_metadata",
                "https://api.example.com/.well-known/oauth-protected-resource",
            ),
            ("Bearer error=invalid_token", "error", "invalid_token"),
            # Multiple parameters with quoted value
            (
                'Bearer realm="api", scope="admin:write resource:read", error="insufficient_scope"',
                "scope",
                "admin:write resource:read",
            ),
            (
                'Bearer realm="api", resource_metadata="https://api.example.com/.well-known/oauth-protected-resource", '
                'error="insufficient_scope"',
                "resource_metadata",
                "https://api.example.com/.well-known/oauth-protected-resource",
            ),
            # Multiple parameters with unquoted value
            ('Bearer realm="api", scope=basic', "scope", "basic"),
            # Values with special characters
            (
                'Bearer scope="resource:read resource:write user_profile"',
                "scope",
                "resource:read resource:write user_profile",
            ),
            (
                'Bearer resource_metadata="https://api.example.com/auth/metadata?version=1"',
                "resource_metadata",
                "https://api.example.com/auth/metadata?version=1",
            ),
        ],
    )
    def test_extract_field_from_www_auth_valid_cases(
        self,
        client_metadata: OAuthClientMetadata,
        mock_storage: MockTokenStorage,
        www_auth_header: str,
        field_name: str,
        expected_value: str,
    ):
        """Test extraction of various fields from valid WWW-Authenticate headers."""

        init_response = httpx.Response(
            status_code=401,
            headers={"WWW-Authenticate": www_auth_header},
            request=httpx.Request("GET", "https://api.example.com/test"),
        )

        result = extract_field_from_www_auth(init_response, field_name)
        assert result == expected_value

    @pytest.mark.parametrize(
        "www_auth_header,field_name,description",
        [
            # No header
            (None, "scope", "no WWW-Authenticate header"),
            # Empty header
            ("", "scope", "empty WWW-Authenticate header"),
            # Header without requested field
            ('Bearer realm="api", error="insufficient_scope"', "scope", "no scope parameter"),
            ('Bearer realm="api", scope="read write"', "resource_metadata", "no resource_metadata parameter"),
            # Malformed field (empty value)
            ("Bearer scope=", "scope", "malformed scope parameter"),
            ("Bearer resource_metadata=", "resource_metadata", "malformed resource_metadata parameter"),
        ],
    )
    def test_extract_field_from_www_auth_invalid_cases(
        self,
        client_metadata: OAuthClientMetadata,
        mock_storage: MockTokenStorage,
        www_auth_header: str | None,
        field_name: str,
        description: str,
    ):
        """Test extraction returns None for invalid cases."""

        headers = {"WWW-Authenticate": www_auth_header} if www_auth_header is not None else {}
        init_response = httpx.Response(
            status_code=401, headers=headers, request=httpx.Request("GET", "https://api.example.com/test")
        )

        result = extract_field_from_www_auth(init_response, field_name)
        assert result is None, f"Should return None for {description}"


class TestCIMD:
    """Test Client ID Metadata Document (CIMD) support."""

    @pytest.mark.parametrize(
        "url,expected",
        [
            # Valid CIMD URLs
            ("https://example.com/client", True),
            ("https://example.com/client-metadata.json", True),
            ("https://example.com/path/to/client", True),
            ("https://example.com:8443/client", True),
            # Invalid URLs - HTTP (not HTTPS)
            ("http://example.com/client", False),
            # Invalid URLs - root path
            ("https://example.com", False),
            ("https://example.com/", False),
            # Invalid URLs - None or empty
            (None, False),
            ("", False),
            # Invalid URLs - malformed (triggers urlparse exception)
            ("http://[::1/foo/", False),
        ],
    )
    def test_is_valid_client_metadata_url(self, url: str | None, expected: bool):
        """Test CIMD URL validation."""
        assert is_valid_client_metadata_url(url) == expected

    def test_should_use_client_metadata_url_when_server_supports(self):
        """Test that CIMD is used when server supports it and URL is provided."""
        oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://auth.example.com"),
            authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
            client_id_metadata_document_supported=True,
        )
        assert should_use_client_metadata_url(oauth_metadata, "https://example.com/client") is True

    def test_should_not_use_client_metadata_url_when_server_does_not_support(self):
        """Test that CIMD is not used when server doesn't support it."""
        oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://auth.example.com"),
            authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
            client_id_metadata_document_supported=False,
        )
        assert should_use_client_metadata_url(oauth_metadata, "https://example.com/client") is False

    def test_should_not_use_client_metadata_url_when_not_provided(self):
        """Test that CIMD is not used when no URL is provided."""
        oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://auth.example.com"),
            authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
            client_id_metadata_document_supported=True,
        )
        assert should_use_client_metadata_url(oauth_metadata, None) is False

    def test_should_not_use_client_metadata_url_when_no_metadata(self):
        """Test that CIMD is not used when OAuth metadata is None."""
        assert should_use_client_metadata_url(None, "https://example.com/client") is False

    def test_create_client_info_from_metadata_url(self):
        """Test creating client info from CIMD URL."""
        client_info = create_client_info_from_metadata_url(
            "https://example.com/client",
            redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        )
        assert client_info.client_id == "https://example.com/client"
        assert client_info.token_endpoint_auth_method == "none"
        assert client_info.redirect_uris == [AnyUrl("http://localhost:3030/callback")]
        assert client_info.client_secret is None

    def test_oauth_provider_with_valid_client_metadata_url(
        self, client_metadata: OAuthClientMetadata, mock_storage: MockTokenStorage
    ):
        """Test OAuthClientProvider initialization with valid client_metadata_url."""

        async def redirect_handler(url: str) -> None:
            pass  # pragma: no cover

        async def callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "test_state"  # pragma: no cover

        provider = OAuthClientProvider(
            server_url="https://api.example.com/v1/mcp",
            client_metadata=client_metadata,
            storage=mock_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
            client_metadata_url="https://example.com/client",
        )
        assert provider.context.client_metadata_url == "https://example.com/client"

    def test_oauth_provider_with_invalid_client_metadata_url_raises_error(
        self, client_metadata: OAuthClientMetadata, mock_storage: MockTokenStorage
    ):
        """Test OAuthClientProvider raises error for invalid client_metadata_url."""

        async def redirect_handler(url: str) -> None:
            pass  # pragma: no cover

        async def callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "test_state"  # pragma: no cover

        with pytest.raises(ValueError) as exc_info:
            OAuthClientProvider(
                server_url="https://api.example.com/v1/mcp",
                client_metadata=client_metadata,
                storage=mock_storage,
                redirect_handler=redirect_handler,
                callback_handler=callback_handler,
                client_metadata_url="http://example.com/client",  # HTTP instead of HTTPS
            )
        assert "HTTPS URL with a non-root pathname" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_auth_flow_uses_cimd_when_server_supports(
        self, client_metadata: OAuthClientMetadata, mock_storage: MockTokenStorage
    ):
        """Test that auth flow uses CIMD URL as client_id when server supports it."""

        async def redirect_handler(url: str) -> None:
            pass  # pragma: no cover

        async def callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "test_state"  # pragma: no cover

        provider = OAuthClientProvider(
            server_url="https://api.example.com/v1/mcp",
            client_metadata=client_metadata,
            storage=mock_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
            client_metadata_url="https://example.com/client",
        )

        provider.context.current_tokens = None
        provider.context.token_expiry_time = None
        provider._initialized = True

        test_request = httpx.Request("GET", "https://api.example.com/v1/mcp")
        auth_flow = provider.async_auth_flow(test_request)

        # First request
        request = await auth_flow.__anext__()
        assert "Authorization" not in request.headers

        # Send 401 response
        response = httpx.Response(401, headers={}, request=test_request)

        # PRM discovery
        prm_request = await auth_flow.asend(response)
        prm_response = httpx.Response(
            200,
            content=b'{"resource": "https://api.example.com/v1/mcp", "authorization_servers": ["https://auth.example.com"]}',
            request=prm_request,
        )

        # OAuth metadata discovery
        oauth_request = await auth_flow.asend(prm_response)
        oauth_response = httpx.Response(
            200,
            content=(
                b'{"issuer": "https://auth.example.com", '
                b'"authorization_endpoint": "https://auth.example.com/authorize", '
                b'"token_endpoint": "https://auth.example.com/token", '
                b'"client_id_metadata_document_supported": true}'
            ),
            request=oauth_request,
        )

        # Mock authorization
        provider._perform_authorization_code_grant = mock.AsyncMock(
            return_value=("test_auth_code", "test_code_verifier")
        )

        # Should skip DCR and go directly to token exchange
        token_request = await auth_flow.asend(oauth_response)
        assert token_request.method == "POST"
        assert str(token_request.url) == "https://auth.example.com/token"

        # Verify client_id is the CIMD URL
        content = token_request.content.decode()
        assert "client_id=https%3A%2F%2Fexample.com%2Fclient" in content

        # Verify client info was set correctly
        assert provider.context.client_info is not None
        assert provider.context.client_info.client_id == "https://example.com/client"
        assert provider.context.client_info.token_endpoint_auth_method == "none"

        # Complete the flow
        token_response = httpx.Response(
            200,
            content=b'{"access_token": "test_token", "token_type": "Bearer", "expires_in": 3600}',
            request=token_request,
        )

        final_request = await auth_flow.asend(token_response)
        assert final_request.headers["Authorization"] == "Bearer test_token"

        final_response = httpx.Response(200, request=final_request)
        try:
            await auth_flow.asend(final_response)
        except StopAsyncIteration:
            pass

    @pytest.mark.anyio
    async def test_auth_flow_falls_back_to_dcr_when_no_cimd_support(
        self, client_metadata: OAuthClientMetadata, mock_storage: MockTokenStorage
    ):
        """Test that auth flow falls back to DCR when server doesn't support CIMD."""

        async def redirect_handler(url: str) -> None:
            pass  # pragma: no cover

        async def callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "test_state"  # pragma: no cover

        provider = OAuthClientProvider(
            server_url="https://api.example.com/v1/mcp",
            client_metadata=client_metadata,
            storage=mock_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
            client_metadata_url="https://example.com/client",
        )

        provider.context.current_tokens = None
        provider.context.token_expiry_time = None
        provider._initialized = True

        test_request = httpx.Request("GET", "https://api.example.com/v1/mcp")
        auth_flow = provider.async_auth_flow(test_request)

        # First request
        await auth_flow.__anext__()

        # Send 401 response
        response = httpx.Response(401, headers={}, request=test_request)

        # PRM discovery
        prm_request = await auth_flow.asend(response)
        prm_response = httpx.Response(
            200,
            content=b'{"resource": "https://api.example.com/v1/mcp", "authorization_servers": ["https://auth.example.com"]}',
            request=prm_request,
        )

        # OAuth metadata discovery - server does NOT support CIMD
        oauth_request = await auth_flow.asend(prm_response)
        oauth_response = httpx.Response(
            200,
            content=(
                b'{"issuer": "https://auth.example.com", '
                b'"authorization_endpoint": "https://auth.example.com/authorize", '
                b'"token_endpoint": "https://auth.example.com/token", '
                b'"registration_endpoint": "https://auth.example.com/register"}'
            ),
            request=oauth_request,
        )

        # Should proceed to DCR instead of skipping it
        registration_request = await auth_flow.asend(oauth_response)
        assert registration_request.method == "POST"
        assert str(registration_request.url) == "https://auth.example.com/register"

        # Complete the flow to avoid generator cleanup issues
        registration_response = httpx.Response(
            201,
            content=b'{"client_id": "dcr_client_id", "redirect_uris": ["http://localhost:3030/callback"]}',
            request=registration_request,
        )

        # Mock authorization
        provider._perform_authorization_code_grant = mock.AsyncMock(
            return_value=("test_auth_code", "test_code_verifier")
        )

        token_request = await auth_flow.asend(registration_response)
        token_response = httpx.Response(
            200,
            content=b'{"access_token": "test_token", "token_type": "Bearer", "expires_in": 3600}',
            request=token_request,
        )

        final_request = await auth_flow.asend(token_response)
        final_response = httpx.Response(200, request=final_request)
        try:
            await auth_flow.asend(final_response)
        except StopAsyncIteration:
            pass
