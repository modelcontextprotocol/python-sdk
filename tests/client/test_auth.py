"""Unit tests for OAuth authorization functionality."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import AnyHttpUrl

from mcp.client.auth import OAuthAuthorization, OAuthClientProvider
from mcp.shared.auth import (
    OAuthClientInformation,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)


class MockOAuthProvider(OAuthClientProvider):
    """Mock OAuth provider for testing."""

    def __init__(self):
        self.redirect_url = "http://localhost:8080/callback"
        self.client_metadata = OAuthClientMetadata(
            client_name="Test Client",
            redirect_uris=[AnyHttpUrl("http://localhost:8080/callback")],
            token_endpoint_auth_method="client_secret_post",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        )
        self.client_info = None
        self.token = None
        self.code_verifier = None
        self.redirect_called = False

    def get_redirect_url(self) -> str:
        return self.redirect_url

    def get_client_metadata(self) -> OAuthClientMetadata:
        return self.client_metadata

    def get_client_information(self) -> OAuthClientInformation | None:
        return self.client_info

    def save_client_information(self, client_information: OAuthClientInformationFull):
        self.client_info = OAuthClientInformation(**client_information.model_dump())

    def get_token(self) -> OAuthToken | None:
        return self.token

    def save_token(self, token: OAuthToken):
        self.token = token

    def redirect_to_authorization(self, authorization_url: str):
        self.redirect_called = True

    def get_code_verifier(self) -> str:
        return self.code_verifier

    def save_code_verifier(self, pkce_code_verifier: str):
        self.code_verifier = pkce_code_verifier


@pytest.fixture
def mock_provider():
    """Create a mock OAuth provider."""
    return MockOAuthProvider()


@pytest.fixture
def auth(mock_provider):
    """Create an OAuthAuthorization instance with a mock provider."""
    return OAuthAuthorization(mock_provider, "http://localhost:8080")


@pytest.mark.anyio
async def test_authorize_with_valid_token(auth, mock_provider):
    """Test authorization with a valid existing token."""
    mock_provider.token = OAuthToken(
        access_token="valid_token",
        token_type="bearer",
        expires_in=3600,
    )

    token = await auth.authorize()
    assert token == mock_provider.token
    assert not mock_provider.redirect_called


@pytest.mark.anyio
async def test_authorize_with_expired_token_and_refresh(auth, mock_provider):
    """Test authorization with an expired token that can be refreshed."""
    mock_provider.token = OAuthToken(
        access_token="old_token",
        token_type="bearer",
        expires_in=0,
        refresh_token="refresh_token",
    )

    with patch.object(
        auth, "refresh_authorization", new_callable=AsyncMock
    ) as mock_refresh:
        mock_refresh.return_value = OAuthToken(
            access_token="new_token",
            token_type="bearer",
            expires_in=3600,
        )

        token = await auth.authorize()
        assert token.access_token == "new_token"
        assert mock_provider.token.access_token == "new_token"
        mock_refresh.assert_called_once_with("refresh_token")


@pytest.mark.anyio
async def test_authorize_with_authorization_code(auth, mock_provider):
    """Test authorization with an authorization code."""
    with patch.object(
        auth, "exchange_authorization", new_callable=AsyncMock
    ) as mock_exchange:
        mock_exchange.return_value = OAuthToken(
            access_token="new_token",
            token_type="bearer",
            expires_in=3600,
        )

        token = await auth.authorize("auth_code")
        assert token.access_token == "new_token"
        assert mock_provider.token.access_token == "new_token"
        mock_exchange.assert_called_once_with("auth_code")


@pytest.mark.anyio
async def test_discover_oauth_metadata(auth):
    """Test OAuth metadata discovery."""
    mock_metadata = OAuthMetadata(
        issuer=AnyHttpUrl("http://localhost:8080"),
        authorization_endpoint=AnyHttpUrl("http://localhost:8080/authorize"),
        token_endpoint=AnyHttpUrl("http://localhost:8080/token"),
        registration_endpoint=AnyHttpUrl("http://localhost:8080/register"),
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        token_endpoint_auth_methods_supported=["client_secret_post"],
        code_challenge_methods_supported=["S256"],
    )

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_metadata.model_dump(),
        )

        metadata = await auth.discover_oauth_metadata()
        assert metadata == mock_metadata


@pytest.mark.anyio
async def test_discover_oauth_metadata_not_found(auth):
    """Test OAuth metadata discovery when endpoint returns 404."""
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=404)

        metadata = await auth.discover_oauth_metadata()
        assert metadata is None


@pytest.mark.anyio
async def test_register_client(auth, mock_provider):
    """Test client registration."""
    mock_client_info = OAuthClientInformationFull(
        client_id="test_client",
        client_secret="test_secret",
        client_name="Test Client",
        redirect_uris=[AnyHttpUrl("http://localhost:8080/callback")],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_client_info.model_dump(),
        )

        client_info = await auth.register_client(None, mock_provider.client_metadata)
        assert client_info == mock_client_info


@pytest.mark.anyio
async def test_register_client_error(auth, mock_provider):
    """Test client registration error handling."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=400,
            text="Invalid request",
        )

        with pytest.raises(ValueError, match="Dynamic client registration failed"):
            await auth.register_client(None, mock_provider.client_metadata)


@pytest.mark.anyio
async def test_exchange_authorization(auth, mock_provider):
    """Test authorization code exchange."""
    mock_provider.code_verifier = "code_verifier"
    mock_token = OAuthToken(
        access_token="new_token",
        token_type="bearer",
        expires_in=3600,
    )

    with patch.object(auth, "_fetch_token", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_token

        token = await auth.exchange_authorization("auth_code")
        assert token == mock_token
        mock_fetch.assert_called_once_with(
            grant_type="authorization_code",
            extra_params={
                "code": "auth_code",
                "code_verifier": "code_verifier",
                "redirect_uri": mock_provider.redirect_url,
            },
        )


@pytest.mark.anyio
async def test_refresh_authorization(auth):
    """Test token refresh."""
    mock_token = OAuthToken(
        access_token="new_token",
        token_type="bearer",
        expires_in=3600,
    )

    with patch.object(auth, "_fetch_token", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_token

        token = await auth.refresh_authorization("refresh_token")
        assert token == mock_token
        mock_fetch.assert_called_once_with(
            grant_type="refresh_token",
            extra_params={"refresh_token": "refresh_token"},
        )


@pytest.mark.anyio
async def test_fetch_token(auth, mock_provider):
    """Test token fetching."""
    mock_provider.client_info = OAuthClientInformation(
        client_id="test_client",
        client_secret="test_secret",
    )
    mock_token = OAuthToken(
        access_token="new_token",
        token_type="bearer",
        expires_in=3600,
    )

    with (
        patch("httpx.AsyncClient.post") as mock_post,
        patch("httpx.AsyncClient.get") as mock_get,
    ):
        mock_get.return_value = MagicMock(status_code=404)
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_token.model_dump(),
        )

        token = await auth._fetch_token(
            "authorization_code",
            {"code": "auth_code", "code_verifier": "verifier"},
        )
        assert token == mock_token
        mock_post.assert_called_once()


@pytest.mark.anyio
async def test_fetch_token_error(auth, mock_provider):
    """Test token fetching error handling."""
    mock_provider.client_info = OAuthClientInformation(
        client_id="test_client",
        client_secret="test_secret",
    )

    with (
        patch("httpx.AsyncClient.post") as mock_post,
        patch("httpx.AsyncClient.get") as mock_get,
    ):
        mock_get.return_value = MagicMock(status_code=404)
        mock_post.return_value = MagicMock(
            status_code=400,
            text="Invalid request",
        )

        with pytest.raises(ValueError, match="Token request failed"):
            await auth._fetch_token(
                "authorization_code",
                {"code": "auth_code", "code_verifier": "verifier"},
            )


@pytest.mark.anyio
async def test_start_authorization_with_metadata(auth, mock_provider):
    """Test starting authorization with OAuth metadata."""
    mock_metadata = OAuthMetadata(
        issuer=AnyHttpUrl("http://localhost:8080"),
        authorization_endpoint=AnyHttpUrl(
            "http://localhost:8080/metadataUrl/authorize"
        ),
        token_endpoint=AnyHttpUrl("http://localhost:8080/token"),
        registration_endpoint=AnyHttpUrl("http://localhost:8080/register"),
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        token_endpoint_auth_methods_supported=["client_secret_post"],
        code_challenge_methods_supported=["S256"],
    )

    mock_provider.client_info = OAuthClientInformation(
        client_id="test_client",
        client_secret="test_secret",
    )

    with patch.object(
        auth, "discover_oauth_metadata", new_callable=AsyncMock
    ) as mock_discover:
        mock_discover.return_value = mock_metadata

        auth_url, code_verifier = await auth.start_authorization()

        # Verify the authorization URL components
        assert "http://localhost:8080/metadataUrl/authorize" in auth_url
        assert "response_type=code" in auth_url
        assert "client_id=test_client" in auth_url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fcallback" in auth_url
        assert "code_challenge_method=S256" in auth_url
        assert "code_challenge=" in auth_url

        # Verify code verifier is generated
        assert code_verifier is not None
        assert len(code_verifier) > 0


@pytest.mark.anyio
async def test_start_authorization_without_metadata(auth, mock_provider):
    """Test starting authorization without OAuth metadata."""
    mock_provider.client_info = OAuthClientInformation(
        client_id="test_client",
        client_secret="test_secret",
    )

    with patch.object(
        auth, "discover_oauth_metadata", new_callable=AsyncMock
    ) as mock_discover:
        mock_discover.return_value = None

        auth_url, code_verifier = await auth.start_authorization()

        # Verify the authorization URL components
        assert "http://localhost:8080/authorize" in auth_url
        assert "response_type=code" in auth_url
        assert "client_id=test_client" in auth_url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fcallback" in auth_url
        assert "code_challenge_method=S256" in auth_url
        assert "code_challenge=" in auth_url

        # Verify code verifier is generated
        assert code_verifier is not None
        assert len(code_verifier) > 0


@pytest.mark.anyio
async def test_authorize_without_token_or_code_verifies_pkce(auth, mock_provider):
    """Test that authorization without token or code properly handles PKCE."""
    mock_provider.client_info = OAuthClientInformation(
        client_id="test_client",
        client_secret="test_secret",
    )

    with patch.object(
        auth, "start_authorization", new_callable=AsyncMock
    ) as mock_start:
        mock_start.return_value = (
            "http://localhost:8080/authorize?code_challenge=xyz",
            "code_verifier",
        )

        token = await auth.authorize()

        # Verify PKCE flow
        assert token is None
        assert mock_provider.redirect_called
        assert mock_provider.code_verifier == "code_verifier"
        mock_start.assert_called_once()

        # Verify the code verifier is saved before redirect
        assert mock_provider.code_verifier == "code_verifier"
