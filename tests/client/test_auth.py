"""
Tests for OAuth client authentication implementation.
"""

import base64
import hashlib
import time
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pydantic import AnyHttpUrl

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
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
        redirect_uris=[AnyHttpUrl("http://localhost:3000/callback")],
        client_name="Test Client",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="read write",
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
        grant_types_supported=["authorization_code", "refresh_token"],
        code_challenge_methods_supported=["S256"],
    )


@pytest.fixture
def oauth_client_info():
    return OAuthClientInformationFull(
        client_id="test_client_id",
        client_secret="test_client_secret",
        redirect_uris=[AnyHttpUrl("http://localhost:3000/callback")],
        client_name="Test Client",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="read write",
    )


@pytest.fixture
def oauth_token():
    return OAuthToken(
        access_token="test_access_token",
        token_type="bearer",
        expires_in=3600,
        refresh_token="test_refresh_token",
        scope="read write",
    )


@pytest.fixture
async def oauth_provider(client_metadata, mock_storage):
    async def mock_redirect_handler(url: str) -> None:
        pass

    async def mock_callback_handler() -> tuple[str, str | None]:
        return "test_auth_code", "test_state"

    return OAuthClientProvider(
        server_url="https://api.example.com/v1/mcp",
        client_metadata=client_metadata,
        storage=mock_storage,
        redirect_handler=mock_redirect_handler,
        callback_handler=mock_callback_handler,
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

    def test_generate_code_verifier(self, oauth_provider):
        """Test PKCE code verifier generation."""
        verifier = oauth_provider._generate_code_verifier()

        # Check length (128 characters)
        assert len(verifier) == 128

        # Check charset (RFC 7636: A-Z, a-z, 0-9, "-", ".", "_", "~")
        allowed_chars = set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
        )
        assert set(verifier) <= allowed_chars

        # Check uniqueness (generate multiple and ensure they're different)
        verifiers = {oauth_provider._generate_code_verifier() for _ in range(10)}
        assert len(verifiers) == 10

    def test_generate_code_challenge(self, oauth_provider):
        """Test PKCE code challenge generation."""
        verifier = "test_code_verifier_123"
        challenge = oauth_provider._generate_code_challenge(verifier)

        # Manually calculate expected challenge
        expected_digest = hashlib.sha256(verifier.encode()).digest()
        expected_challenge = (
            base64.urlsafe_b64encode(expected_digest).decode().rstrip("=")
        )

        assert challenge == expected_challenge

        # Verify it's base64url without padding
        assert "=" not in challenge
        assert "+" not in challenge
        assert "/" not in challenge

    def test_get_authorization_base_url(self, oauth_provider):
        """Test authorization base URL extraction."""
        # Test with path
        assert (
            oauth_provider._get_authorization_base_url("https://api.example.com/v1/mcp")
            == "https://api.example.com"
        )

        # Test with no path
        assert (
            oauth_provider._get_authorization_base_url("https://api.example.com")
            == "https://api.example.com"
        )

        # Test with port
        assert (
            oauth_provider._get_authorization_base_url(
                "https://api.example.com:8080/path/to/mcp"
            )
            == "https://api.example.com:8080"
        )

    @pytest.mark.anyio
    async def test_discover_oauth_metadata_success(
        self, oauth_provider, oauth_metadata
    ):
        """Test successful OAuth metadata discovery."""
        metadata_response = oauth_metadata.model_dump(by_alias=True, mode="json")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = metadata_response
            mock_client.get.return_value = mock_response

            result = await oauth_provider._discover_oauth_metadata(
                "https://api.example.com/v1/mcp"
            )

            assert result is not None
            assert (
                result.authorization_endpoint == oauth_metadata.authorization_endpoint
            )
            assert result.token_endpoint == oauth_metadata.token_endpoint

            # Verify correct URL was called
            mock_client.get.assert_called_once()
            call_args = mock_client.get.call_args[0]
            assert (
                call_args[0]
                == "https://api.example.com/.well-known/oauth-authorization-server"
            )

    @pytest.mark.anyio
    async def test_discover_oauth_metadata_not_found(self, oauth_provider):
        """Test OAuth metadata discovery when not found."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 404
            mock_client.get.return_value = mock_response

            result = await oauth_provider._discover_oauth_metadata(
                "https://api.example.com/v1/mcp"
            )

            assert result is None

    @pytest.mark.anyio
    async def test_discover_oauth_metadata_cors_fallback(
        self, oauth_provider, oauth_metadata
    ):
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

            result = await oauth_provider._discover_oauth_metadata(
                "https://api.example.com/v1/mcp"
            )

            assert result is not None
            assert mock_client.get.call_count == 2

    @pytest.mark.anyio
    async def test_register_oauth_client_success(
        self, oauth_provider, oauth_metadata, oauth_client_info
    ):
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
    async def test_register_oauth_client_fallback_endpoint(
        self, oauth_provider, oauth_client_info
    ):
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
            with patch.object(
                oauth_provider, "_discover_oauth_metadata", return_value=None
            ):
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
            with patch.object(
                oauth_provider, "_discover_oauth_metadata", return_value=None
            ):
                with pytest.raises(httpx.HTTPStatusError):
                    await oauth_provider._register_oauth_client(
                        "https://api.example.com/v1/mcp",
                        oauth_provider.client_metadata,
                        None,
                    )

    def test_has_valid_token_no_token(self, oauth_provider):
        """Test token validation with no token."""
        assert not oauth_provider._has_valid_token()

    def test_has_valid_token_valid(self, oauth_provider, oauth_token):
        """Test token validation with valid token."""
        oauth_provider._current_tokens = oauth_token
        oauth_provider._token_expiry_time = time.time() + 3600  # Future expiry

        assert oauth_provider._has_valid_token()

    def test_has_valid_token_expired(self, oauth_provider, oauth_token):
        """Test token validation with expired token."""
        oauth_provider._current_tokens = oauth_token
        oauth_provider._token_expiry_time = time.time() - 3600  # Past expiry

        assert not oauth_provider._has_valid_token()

    @pytest.mark.anyio
    async def test_validate_token_scopes_no_scope(self, oauth_provider):
        """Test scope validation with no scope returned."""
        token = OAuthToken(access_token="test", token_type="bearer")

        # Should not raise exception
        await oauth_provider._validate_token_scopes(token)

    @pytest.mark.anyio
    async def test_validate_token_scopes_valid(self, oauth_provider, client_metadata):
        """Test scope validation with valid scopes."""
        oauth_provider.client_metadata = client_metadata
        token = OAuthToken(
            access_token="test",
            token_type="bearer",
            scope="read write",
        )

        # Should not raise exception
        await oauth_provider._validate_token_scopes(token)

    @pytest.mark.anyio
    async def test_validate_token_scopes_subset(self, oauth_provider, client_metadata):
        """Test scope validation with subset of requested scopes."""
        oauth_provider.client_metadata = client_metadata
        token = OAuthToken(
            access_token="test",
            token_type="bearer",
            scope="read",
        )

        # Should not raise exception (servers can grant subset)
        await oauth_provider._validate_token_scopes(token)

    @pytest.mark.anyio
    async def test_validate_token_scopes_unauthorized(
        self, oauth_provider, client_metadata
    ):
        """Test scope validation with unauthorized scopes."""
        oauth_provider.client_metadata = client_metadata
        token = OAuthToken(
            access_token="test",
            token_type="bearer",
            scope="read write admin",  # Includes unauthorized "admin"
        )

        with pytest.raises(Exception, match="Server granted unauthorized scopes"):
            await oauth_provider._validate_token_scopes(token)

    @pytest.mark.anyio
    async def test_validate_token_scopes_no_requested(self, oauth_provider):
        """Test scope validation with no requested scopes accepts any server scopes."""
        # No scope in client metadata
        oauth_provider.client_metadata.scope = None
        token = OAuthToken(
            access_token="test",
            token_type="bearer",
            scope="admin super",
        )

        # Should not raise exception when no scopes were explicitly requested
        # (accepts server defaults)
        await oauth_provider._validate_token_scopes(token)

    @pytest.mark.anyio
    async def test_initialize(
        self, oauth_provider, mock_storage, oauth_token, oauth_client_info
    ):
        """Test initialization loading from storage."""
        mock_storage._tokens = oauth_token
        mock_storage._client_info = oauth_client_info

        await oauth_provider.initialize()

        assert oauth_provider._current_tokens == oauth_token
        assert oauth_provider._client_info == oauth_client_info

    @pytest.mark.anyio
    async def test_get_or_register_client_existing(
        self, oauth_provider, oauth_client_info
    ):
        """Test getting existing client info."""
        oauth_provider._client_info = oauth_client_info

        result = await oauth_provider._get_or_register_client()

        assert result == oauth_client_info

    @pytest.mark.anyio
    async def test_get_or_register_client_register_new(
        self, oauth_provider, oauth_client_info
    ):
        """Test registering new client."""
        with patch.object(
            oauth_provider, "_register_oauth_client", return_value=oauth_client_info
        ) as mock_register:
            result = await oauth_provider._get_or_register_client()

            assert result == oauth_client_info
            assert oauth_provider._client_info == oauth_client_info
            mock_register.assert_called_once()

    @pytest.mark.anyio
    async def test_exchange_code_for_token_success(
        self, oauth_provider, oauth_client_info, oauth_token
    ):
        """Test successful code exchange for token."""
        oauth_provider._code_verifier = "test_verifier"
        token_response = oauth_token.model_dump(by_alias=True, mode="json")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = token_response
            mock_client.post.return_value = mock_response

            with patch.object(
                oauth_provider, "_validate_token_scopes"
            ) as mock_validate:
                await oauth_provider._exchange_code_for_token(
                    "test_auth_code", oauth_client_info
                )

                assert (
                    oauth_provider._current_tokens.access_token
                    == oauth_token.access_token
                )
                mock_validate.assert_called_once()

    @pytest.mark.anyio
    async def test_exchange_code_for_token_failure(
        self, oauth_provider, oauth_client_info
    ):
        """Test failed code exchange for token."""
        oauth_provider._code_verifier = "test_verifier"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.text = "Invalid grant"
            mock_client.post.return_value = mock_response

            with pytest.raises(Exception, match="Token exchange failed"):
                await oauth_provider._exchange_code_for_token(
                    "invalid_auth_code", oauth_client_info
                )

    @pytest.mark.anyio
    async def test_refresh_access_token_success(
        self, oauth_provider, oauth_client_info, oauth_token
    ):
        """Test successful token refresh."""
        oauth_provider._current_tokens = oauth_token
        oauth_provider._client_info = oauth_client_info

        new_token = OAuthToken(
            access_token="new_access_token",
            token_type="bearer",
            expires_in=3600,
            refresh_token="new_refresh_token",
            scope="read write",
        )
        token_response = new_token.model_dump(by_alias=True, mode="json")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = token_response
            mock_client.post.return_value = mock_response

            with patch.object(
                oauth_provider, "_validate_token_scopes"
            ) as mock_validate:
                result = await oauth_provider._refresh_access_token()

                assert result is True
                assert (
                    oauth_provider._current_tokens.access_token
                    == new_token.access_token
                )
                mock_validate.assert_called_once()

    @pytest.mark.anyio
    async def test_refresh_access_token_no_refresh_token(self, oauth_provider):
        """Test token refresh with no refresh token."""
        oauth_provider._current_tokens = OAuthToken(
            access_token="test",
            token_type="bearer",
            # No refresh_token
        )

        result = await oauth_provider._refresh_access_token()
        assert result is False

    @pytest.mark.anyio
    async def test_refresh_access_token_failure(
        self, oauth_provider, oauth_client_info, oauth_token
    ):
        """Test failed token refresh."""
        oauth_provider._current_tokens = oauth_token
        oauth_provider._client_info = oauth_client_info

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 400
            mock_client.post.return_value = mock_response

            result = await oauth_provider._refresh_access_token()
            assert result is False

    @pytest.mark.anyio
    async def test_perform_oauth_flow_success(
        self, oauth_provider, oauth_metadata, oauth_client_info
    ):
        """Test successful OAuth flow."""
        oauth_provider._metadata = oauth_metadata
        oauth_provider._client_info = oauth_client_info

        # Mock the redirect handler to capture the auth URL
        auth_url_captured = None

        async def mock_redirect_handler(url: str) -> None:
            nonlocal auth_url_captured
            auth_url_captured = url

        oauth_provider.redirect_handler = mock_redirect_handler

        # Mock callback handler with matching state
        async def mock_callback_handler() -> tuple[str, str | None]:
            # Extract state from auth URL to return matching value
            if auth_url_captured:
                parsed_url = urlparse(auth_url_captured)
                query_params = parse_qs(parsed_url.query)
                state = query_params.get("state", [None])[0]
                return "test_auth_code", state
            return "test_auth_code", "test_state"

        oauth_provider.callback_handler = mock_callback_handler

        with patch.object(oauth_provider, "_exchange_code_for_token") as mock_exchange:
            await oauth_provider._perform_oauth_flow()

            # Verify auth URL was generated correctly
            assert auth_url_captured is not None
            parsed_url = urlparse(auth_url_captured)
            query_params = parse_qs(parsed_url.query)

            assert query_params["response_type"][0] == "code"
            assert query_params["client_id"][0] == oauth_client_info.client_id
            assert query_params["code_challenge_method"][0] == "S256"
            assert "code_challenge" in query_params
            assert "state" in query_params

            # Verify code exchange was called
            mock_exchange.assert_called_once_with("test_auth_code", oauth_client_info)

    @pytest.mark.anyio
    async def test_perform_oauth_flow_state_mismatch(
        self, oauth_provider, oauth_metadata, oauth_client_info
    ):
        """Test OAuth flow with state parameter mismatch."""
        oauth_provider._metadata = oauth_metadata
        oauth_provider._client_info = oauth_client_info

        # Mock callback handler to return mismatched state
        async def mock_callback_handler() -> tuple[str, str | None]:
            return "test_auth_code", "wrong_state"

        oauth_provider.callback_handler = mock_callback_handler

        async def mock_redirect_handler(url: str) -> None:
            pass

        oauth_provider.redirect_handler = mock_redirect_handler

        with pytest.raises(Exception, match="State parameter mismatch"):
            await oauth_provider._perform_oauth_flow()

    @pytest.mark.anyio
    async def test_ensure_token_existing_valid(self, oauth_provider, oauth_token):
        """Test ensure_token with existing valid token."""
        oauth_provider._current_tokens = oauth_token
        oauth_provider._token_expiry_time = time.time() + 3600

        await oauth_provider.ensure_token()

        # Should not trigger new auth flow
        assert oauth_provider._current_tokens == oauth_token

    @pytest.mark.anyio
    async def test_ensure_token_refresh(self, oauth_provider, oauth_token):
        """Test ensure_token with expired token that can be refreshed."""
        oauth_provider._current_tokens = oauth_token
        oauth_provider._token_expiry_time = time.time() - 3600  # Expired

        with patch.object(
            oauth_provider, "_refresh_access_token", return_value=True
        ) as mock_refresh:
            await oauth_provider.ensure_token()
            mock_refresh.assert_called_once()

    @pytest.mark.anyio
    async def test_ensure_token_full_flow(self, oauth_provider):
        """Test ensure_token triggering full OAuth flow."""
        # No existing token
        with patch.object(oauth_provider, "_perform_oauth_flow") as mock_flow:
            await oauth_provider.ensure_token()
            mock_flow.assert_called_once()

    @pytest.mark.anyio
    async def test_async_auth_flow_add_token(self, oauth_provider, oauth_token):
        """Test async auth flow adding Bearer token to request."""
        oauth_provider._current_tokens = oauth_token
        oauth_provider._token_expiry_time = time.time() + 3600

        request = httpx.Request("GET", "https://api.example.com/data")

        # Mock response
        mock_response = Mock()
        mock_response.status_code = 200

        auth_flow = oauth_provider.async_auth_flow(request)
        updated_request = await auth_flow.__anext__()

        assert (
            updated_request.headers["Authorization"]
            == f"Bearer {oauth_token.access_token}"
        )

        # Send mock response
        try:
            await auth_flow.asend(mock_response)
        except StopAsyncIteration:
            pass

    @pytest.mark.anyio
    async def test_async_auth_flow_401_response(self, oauth_provider, oauth_token):
        """Test async auth flow handling 401 response."""
        oauth_provider._current_tokens = oauth_token
        oauth_provider._token_expiry_time = time.time() + 3600

        request = httpx.Request("GET", "https://api.example.com/data")

        # Mock 401 response
        mock_response = Mock()
        mock_response.status_code = 401

        auth_flow = oauth_provider.async_auth_flow(request)
        await auth_flow.__anext__()

        # Send 401 response
        try:
            await auth_flow.asend(mock_response)
        except StopAsyncIteration:
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

    def test_scope_priority_client_metadata_first(
        self, oauth_provider, oauth_client_info
    ):
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
        elif (
            hasattr(oauth_provider._client_info, "scope")
            and oauth_provider._client_info.scope
        ):
            auth_params["scope"] = oauth_provider._client_info.scope

        assert auth_params["scope"] == "read write"

    def test_scope_priority_no_client_metadata_scope(
        self, oauth_provider, oauth_client_info
    ):
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

    def test_scope_priority_no_scope(self, oauth_provider, oauth_client_info):
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
        elif (
            hasattr(oauth_provider._client_info, "scope")
            and oauth_provider._client_info.scope
        ):
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
        with patch(
            "mcp.client.auth.secrets.compare_digest", return_value=False
        ) as mock_compare:
            with pytest.raises(Exception, match="State parameter mismatch"):
                await oauth_provider._perform_oauth_flow()

            # Verify constant-time comparison was used
            mock_compare.assert_called_once()

    @pytest.mark.anyio
    async def test_state_parameter_validation_none_state(
        self, oauth_provider, oauth_metadata, oauth_client_info
    ):
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
                await oauth_provider._exchange_code_for_token(
                    "invalid_auth_code", oauth_client_info
                )
