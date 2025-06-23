"""
Tests for refactored OAuth client authentication implementation.
"""

# <<<<<<< main
import asyncio
import base64
import hashlib
# =======
# >>>>>>> main
import time

import httpx
import pytest
from pydantic import AnyHttpUrl, AnyUrl

# <<<<<<< main
from mcp.client.auth import (
    ClientCredentialsProvider,
    OAuthClientProvider,
    TokenExchangeProvider,
    _discover_oauth_metadata,
    _get_authorization_base_url,
)
from mcp.server.auth.routes import build_metadata
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
# =======
# from mcp.client.auth import OAuthClientProvider, PKCEParameters
# >>>>>>> main
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
# <<<<<<< main
def client_credentials_metadata():
    return OAuthClientMetadata(
        redirect_uris=[AnyHttpUrl("http://localhost:3000/callback")],
        client_name="CC Client",
        grant_types=["client_credentials"],
        response_types=["code"],
        scope="read write",
        token_endpoint_auth_method="client_secret_post",
    )


@pytest.fixture
def oauth_metadata():
    return OAuthMetadata(
        issuer=AnyHttpUrl("https://auth.example.com"),
        authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
        token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
        registration_endpoint=AnyHttpUrl("https://auth.example.com/register"),
        scopes_supported=["read", "write", "admin"],
        response_types_supported=["code"],
        grant_types_supported=[
            "authorization_code",
            "refresh_token",
            "client_credentials",
            "token_exchange",
        ],
        code_challenge_methods_supported=["S256"],
    )


@pytest.fixture
def oauth_client_info():
    return OAuthClientInformationFull(
        client_id="test_client_id",
        client_secret="test_client_secret",
        redirect_uris=[AnyUrl("http://localhost:3000/callback")],
        client_name="Test Client",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="read write",
    )


@pytest.fixture
def oauth_token():
# =======
# def valid_tokens():
# >>>>>>> main
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


# <<<<<<< main
@pytest.fixture
async def client_credentials_provider(client_credentials_metadata, mock_storage):
    return ClientCredentialsProvider(
        server_url="https://api.example.com/v1/mcp",
        client_metadata=client_credentials_metadata,
        storage=mock_storage,
    )


@pytest.fixture
async def token_exchange_provider(client_credentials_metadata, mock_storage):
    return TokenExchangeProvider(
        server_url="https://api.example.com/v1/mcp",
        client_metadata=client_credentials_metadata,
        storage=mock_storage,
        subject_token_supplier=lambda: asyncio.sleep(0, result="user_token"),
    )


class TestOAuthClientProvider:
    """Test OAuth client provider functionality."""

    @pytest.mark.anyio
    async def test_init(self, oauth_provider, client_metadata, mock_storage):
        """Test OAuth provider initialization."""
        assert oauth_provider.server_url == "https://api.example.com/v1/mcp"
        assert oauth_provider.client_metadata == client_metadata
        assert oauth_provider.storage == mock_storage
        assert oauth_provider.timeout == 300.0

    @pytest.mark.anyio
    async def test_generate_code_verifier(self, oauth_provider):
        """Test PKCE code verifier generation."""
        verifier = oauth_provider._generate_code_verifier()
# =======
# class TestPKCEParameters:
#     """Test PKCE parameter generation."""

#     def test_pkce_generation(self):
#         """Test PKCE parameter generation creates valid values."""
#         pkce = PKCEParameters.generate()
# >>>>>>> main

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
# <<<<<<< main
        assert _get_authorization_base_url("https://api.example.com/v1/mcp") == "https://api.example.com"

        # Test with no path
        assert _get_authorization_base_url("https://api.example.com") == "https://api.example.com"

        # Test with port
        assert _get_authorization_base_url("https://api.example.com:8080/path/to/mcp") == "https://api.example.com:8080"

    @pytest.mark.anyio
    async def test_discover_oauth_metadata_success(self, oauth_provider, oauth_metadata):
        """Test successful OAuth metadata discovery."""
        metadata_response = oauth_metadata.model_dump(by_alias=True, mode="json")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = metadata_response
            mock_client.get.return_value = mock_response

            result = await _discover_oauth_metadata("https://api.example.com/v1/mcp")

            assert result is not None
            assert result.authorization_endpoint == oauth_metadata.authorization_endpoint
            assert result.token_endpoint == oauth_metadata.token_endpoint

            # Verify correct URL was called
            mock_client.get.assert_called_once()
            call_args = mock_client.get.call_args[0]
            assert call_args[0] == "https://api.example.com/.well-known/oauth-authorization-server"

    @pytest.mark.anyio
    async def test_discover_oauth_metadata_not_found(self, oauth_provider):
        """Test OAuth metadata discovery when not found."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 404
            mock_client.get.return_value = mock_response

            result = await _discover_oauth_metadata("https://api.example.com/v1/mcp")

            assert result is None

    @pytest.mark.anyio
    async def test_discover_oauth_metadata_cors_fallback(self, oauth_provider, oauth_metadata):
        """Test OAuth metadata discovery with CORS fallback."""
        metadata_response = oauth_metadata.model_dump(by_alias=True, mode="json")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # First call fails (CORS), second succeeds
            mock_response_success = Mock()
            mock_response_success.status_code = 200
            mock_response_success.json.return_value = metadata_response

            mock_client.get.side_effect = [
                TypeError("CORS error"),  # First call fails
                mock_response_success,  # Second call succeeds
            ]

            result = await _discover_oauth_metadata("https://api.example.com/v1/mcp")

            assert result is not None
            assert mock_client.get.call_count == 2

    @pytest.mark.anyio
    async def test_register_oauth_client_success(self, oauth_provider, oauth_metadata, oauth_client_info):
        """Test successful OAuth client registration."""
        registration_response = oauth_client_info.model_dump(by_alias=True, mode="json")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 201
            mock_response.json.return_value = registration_response
            mock_client.post.return_value = mock_response

            result = await oauth_provider._register_oauth_client(
                "https://api.example.com/v1/mcp",
                oauth_provider.client_metadata,
                oauth_metadata,
            )

            assert result.client_id == oauth_client_info.client_id
            assert result.client_secret == oauth_client_info.client_secret

            # Verify correct registration endpoint was used
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert call_args[0][0] == str(oauth_metadata.registration_endpoint)

    @pytest.mark.anyio
    async def test_register_oauth_client_fallback_endpoint(self, oauth_provider, oauth_client_info):
        """Test OAuth client registration with fallback endpoint."""
        registration_response = oauth_client_info.model_dump(by_alias=True, mode="json")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 201
            mock_response.json.return_value = registration_response
            mock_client.post.return_value = mock_response

            # Mock metadata discovery to return None (fallback)
            with patch("mcp.client.auth._discover_oauth_metadata", return_value=None):
                result = await oauth_provider._register_oauth_client(
                    "https://api.example.com/v1/mcp",
                    oauth_provider.client_metadata,
                    None,
                )

                assert result.client_id == oauth_client_info.client_id

                # Verify fallback endpoint was used
                mock_client.post.assert_called_once()
                call_args = mock_client.post.call_args
                assert call_args[0][0] == "https://api.example.com/register"

    @pytest.mark.anyio
    async def test_register_oauth_client_failure(self, oauth_provider):
        """Test OAuth client registration failure."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.text = "Bad Request"
            mock_client.post.return_value = mock_response

            # Mock metadata discovery to return None (fallback)
            with patch("mcp.client.auth._discover_oauth_metadata", return_value=None):
                with pytest.raises(httpx.HTTPStatusError):
                    await oauth_provider._register_oauth_client(
                        "https://api.example.com/v1/mcp",
                        oauth_provider.client_metadata,
                        None,
                    )

    @pytest.mark.anyio
    async def test_has_valid_token_no_token(self, oauth_provider):
        """Test token validation with no token."""
        assert not oauth_provider._has_valid_token()

    @pytest.mark.anyio
    async def test_has_valid_token_valid(self, oauth_provider, oauth_token):
        """Test token validation with valid token."""
        oauth_provider._current_tokens = oauth_token
        oauth_provider._token_expiry_time = time.time() + 3600  # Future expiry

        assert oauth_provider._has_valid_token()

    @pytest.mark.anyio
    async def test_has_valid_token_expired(self, oauth_provider, oauth_token):
        """Test token validation with expired token."""
        oauth_provider._current_tokens = oauth_token
        oauth_provider._token_expiry_time = time.time() - 3600  # Past expiry

        assert not oauth_provider._has_valid_token()

    @pytest.mark.anyio
    async def test_validate_token_scopes_no_scope(self, oauth_provider):
        """Test scope validation with no scope returned."""
        token = OAuthToken(access_token="test", token_type="Bearer")

        # Should not raise exception
        await oauth_provider._validate_token_scopes(token)

    @pytest.mark.anyio
    async def test_validate_token_scopes_valid(self, oauth_provider, client_metadata):
        """Test scope validation with valid scopes."""
        oauth_provider.client_metadata = client_metadata
        token = OAuthToken(
            access_token="test",
            token_type="Bearer",
            scope="read write",
# =======
#         assert context.get_authorization_base_url("https://api.example.com/v1/mcp") == "https://api.example.com"

#         # Test with no path
#         assert context.get_authorization_base_url("https://api.example.com") == "https://api.example.com"

#         # Test with port
#         assert (
#             context.get_authorization_base_url("https://api.example.com:8080/path/to/mcp")
#             == "https://api.example.com:8080"
#         )

#         # Test with query params
#         assert (
#             context.get_authorization_base_url("https://api.example.com/path?param=value") == "https://api.example.com"
# >>>>>>> main
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
# <<<<<<< main
            pass

        # Should clear current tokens
        assert oauth_provider._current_tokens is None

    @pytest.mark.anyio
    async def test_async_auth_flow_no_token(self, oauth_provider):
        """Test async auth flow with no token triggers auth flow."""
        request = httpx.Request("GET", "https://api.example.com/data")

        with (
            patch.object(oauth_provider, "initialize") as mock_init,
            patch.object(oauth_provider, "ensure_token") as mock_ensure,
        ):
            auth_flow = oauth_provider.async_auth_flow(request)
            updated_request = await auth_flow.__anext__()

            mock_init.assert_called_once()
            mock_ensure.assert_called_once()

            # No Authorization header should be added if no token
            assert "Authorization" not in updated_request.headers

    @pytest.mark.anyio
    async def test_scope_priority_client_metadata_first(self, oauth_provider, oauth_client_info):
        """Test that client metadata scope takes priority."""
        oauth_provider.client_metadata.scope = "read write"
        oauth_provider._client_info = oauth_client_info
        oauth_provider._client_info.scope = "admin"

        # Build auth params to test scope logic
        auth_params = {
            "response_type": "code",
            "client_id": "test_client",
            "redirect_uri": "http://localhost:3000/callback",
            "state": "test_state",
            "code_challenge": "test_challenge",
            "code_challenge_method": "S256",
        }

        # Apply scope logic from _perform_oauth_flow
        if oauth_provider.client_metadata.scope:
            auth_params["scope"] = oauth_provider.client_metadata.scope
        elif hasattr(oauth_provider._client_info, "scope") and oauth_provider._client_info.scope:
            auth_params["scope"] = oauth_provider._client_info.scope

        assert auth_params["scope"] == "read write"

    @pytest.mark.anyio
    async def test_scope_priority_no_client_metadata_scope(self, oauth_provider, oauth_client_info):
        """Test that no scope parameter is set when client metadata has no scope."""
        oauth_provider.client_metadata.scope = None
        oauth_provider._client_info = oauth_client_info
        oauth_provider._client_info.scope = "admin"

        # Build auth params to test scope logic
        auth_params = {
            "response_type": "code",
            "client_id": "test_client",
            "redirect_uri": "http://localhost:3000/callback",
            "state": "test_state",
            "code_challenge": "test_challenge",
            "code_challenge_method": "S256",
        }

        # Apply simplified scope logic from _perform_oauth_flow
        if oauth_provider.client_metadata.scope:
            auth_params["scope"] = oauth_provider.client_metadata.scope
        # No fallback to client_info scope in simplified logic

        # No scope should be set since client metadata doesn't have explicit scope
        assert "scope" not in auth_params

    @pytest.mark.anyio
    async def test_scope_priority_no_scope(self, oauth_provider, oauth_client_info):
        """Test that no scope parameter is set when no scopes specified."""
        oauth_provider.client_metadata.scope = None
        oauth_provider._client_info = oauth_client_info
        oauth_provider._client_info.scope = None

        # Build auth params to test scope logic
        auth_params = {
            "response_type": "code",
            "client_id": "test_client",
            "redirect_uri": "http://localhost:3000/callback",
            "state": "test_state",
            "code_challenge": "test_challenge",
            "code_challenge_method": "S256",
        }

        # Apply scope logic from _perform_oauth_flow
        if oauth_provider.client_metadata.scope:
            auth_params["scope"] = oauth_provider.client_metadata.scope
        elif hasattr(oauth_provider._client_info, "scope") and oauth_provider._client_info.scope:
            auth_params["scope"] = oauth_provider._client_info.scope

        # No scope should be set
        assert "scope" not in auth_params

    @pytest.mark.anyio
    async def test_state_parameter_validation_uses_constant_time(
        self, oauth_provider, oauth_metadata, oauth_client_info
    ):
        """Test that state parameter validation uses constant-time comparison."""
        oauth_provider._metadata = oauth_metadata
        oauth_provider._client_info = oauth_client_info

        # Mock callback handler to return mismatched state
        async def mock_callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "wrong_state"

        oauth_provider.callback_handler = mock_callback_handler

        async def mock_redirect_handler(url: str) -> None:
            pass

        oauth_provider.redirect_handler = mock_redirect_handler

        # Patch secrets.compare_digest to verify it's being called
        with patch("mcp.client.auth.secrets.compare_digest", return_value=False) as mock_compare:
            with pytest.raises(Exception, match="State parameter mismatch"):
                await oauth_provider._perform_oauth_flow()

            # Verify constant-time comparison was used
            mock_compare.assert_called_once()

    @pytest.mark.anyio
    async def test_state_parameter_validation_none_state(self, oauth_provider, oauth_metadata, oauth_client_info):
        """Test that None state is handled correctly."""
        oauth_provider._metadata = oauth_metadata
        oauth_provider._client_info = oauth_client_info

        # Mock callback handler to return None state
        async def mock_callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", None

        oauth_provider.callback_handler = mock_callback_handler

        async def mock_redirect_handler(url: str) -> None:
            pass

        oauth_provider.redirect_handler = mock_redirect_handler

        with pytest.raises(Exception, match="State parameter mismatch"):
            await oauth_provider._perform_oauth_flow()

    @pytest.mark.anyio
    async def test_token_exchange_error_basic(self, oauth_provider, oauth_client_info):
        """Test token exchange error handling (basic)."""
        oauth_provider._code_verifier = "test_verifier"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock error response
            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.text = "Bad Request"
            mock_client.post.return_value = mock_response

            with pytest.raises(Exception, match="Token exchange failed"):
                await oauth_provider._exchange_code_for_token("invalid_auth_code", oauth_client_info)


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
        pytest.param(
            "https://auth.example.com",
            "https://auth.example.com/docs",
            "https://auth.example.com/authorize",
            "https://auth.example.com/token",
            "https://auth.example.com/register",
            "https://auth.example.com/revoke",
            id="simple-url",
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
    metadata = build_metadata(
        issuer_url=AnyHttpUrl(issuer_url),
        service_documentation_url=AnyHttpUrl(service_documentation_url),
        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=["read", "write", "admin"]),
        revocation_options=RevocationOptions(enabled=True),
    )

    expected = OAuthMetadata(
        issuer=AnyHttpUrl(issuer_url),
        authorization_endpoint=AnyHttpUrl(authorization_endpoint),
        token_endpoint=AnyHttpUrl(token_endpoint),
        registration_endpoint=AnyHttpUrl(registration_endpoint),
        scopes_supported=["read", "write", "admin"],
        grant_types_supported=[
            "authorization_code",
            "refresh_token",
            "client_credentials",
            "token_exchange",
        ],
        token_endpoint_auth_methods_supported=["client_secret_post"],
        service_documentation=AnyHttpUrl(service_documentation_url),
        revocation_endpoint=AnyHttpUrl(revocation_endpoint),
        revocation_endpoint_auth_methods_supported=["client_secret_post"],
        code_challenge_methods_supported=["S256"],
    )

    assert metadata == expected


class TestClientCredentialsProvider:
    @pytest.mark.anyio
    async def test_request_token_success(
        self,
        client_credentials_provider,
        oauth_metadata,
        oauth_client_info,
        oauth_token,
    ):
        client_credentials_provider._metadata = oauth_metadata
        client_credentials_provider._client_info = oauth_client_info

        token_json = oauth_token.model_dump(by_alias=True, mode="json")
        token_json.pop("refresh_token", None)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = token_json
            mock_client.post.return_value = mock_response

            await client_credentials_provider.ensure_token()

            mock_client.post.assert_called_once()
            assert client_credentials_provider._current_tokens.access_token == oauth_token.access_token

    @pytest.mark.anyio
    async def test_async_auth_flow(self, client_credentials_provider, oauth_token):
        client_credentials_provider._current_tokens = oauth_token
        client_credentials_provider._token_expiry_time = time.time() + 3600

        request = httpx.Request("GET", "https://api.example.com/data")
        mock_response = Mock()
        mock_response.status_code = 200

        auth_flow = client_credentials_provider.async_auth_flow(request)
        updated_request = await auth_flow.__anext__()
        assert updated_request.headers["Authorization"] == f"Bearer {oauth_token.access_token}"
        try:
            await auth_flow.asend(mock_response)
        except StopAsyncIteration:
            pass


class TestTokenExchangeProvider:
    @pytest.mark.anyio
    async def test_request_token_success(
        self,
        token_exchange_provider,
        oauth_metadata,
        oauth_client_info,
        oauth_token,
    ):
        token_exchange_provider._metadata = oauth_metadata
        token_exchange_provider._client_info = oauth_client_info

        token_json = oauth_token.model_dump(by_alias=True, mode="json")
        token_json.pop("refresh_token", None)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = token_json
            mock_client.post.return_value = mock_response

            await token_exchange_provider.ensure_token()

            mock_client.post.assert_called_once()
            assert token_exchange_provider._current_tokens.access_token == oauth_token.access_token
# =======
#             pass  # Expected
# >>>>>>> main
