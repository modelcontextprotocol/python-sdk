import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import AnyHttpUrl

from mcp.client.auth.oauth import (
    AccessToken,
    ClientMetadata,
    DynamicClientRegistration,
    OAuthClient,
    OAuthClientProvider,
)


class MockOauthClientProvider(OAuthClientProvider):
    @property
    def client_metadata(self) -> ClientMetadata:
        return ClientMetadata(
            client_name="Test Client",
            redirect_uris=[AnyHttpUrl("https://client.example.com/callback")],
            token_endpoint_auth_method="client_secret_post",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        )

    @property
    def redirect_url(self) -> AnyHttpUrl:
        return AnyHttpUrl("https://client.example.com/callback")

    async def open_user_agent(self, url: AnyHttpUrl) -> None:
        pass

    async def client_registration(
        self, issuer: AnyHttpUrl
    ) -> DynamicClientRegistration | None:
        return None

    async def store_client_registration(
        self, issuer: AnyHttpUrl, metadata: DynamicClientRegistration
    ) -> None:
        pass

    def code_verifier(self) -> str:
        return "test-code-verifier"

    async def token(self) -> AccessToken | None:
        return None

    async def store_token(self, token: AccessToken) -> None:
        pass


@pytest.fixture
def server_url():
    return AnyHttpUrl("https://example.com/v1")


@pytest.fixture
def http_server_urls():
    return [
        # HTTP URL should be converted to HTTPS
        "http://example.com/auth",
        # URL with trailing slash
        "http://auth.example.org/",
        # Complex path
        "http://api.example.net/v1/auth/service",
        # URL with query parameters (these should be ignored)
        "http://example.io/oauth?version=2.0&debug=true",
        # URL with port
        "http://auth.example.com:8080/v1",
    ]


@pytest.fixture
def auth_client(server_url):
    return OAuthClient(server_url, MockOauthClientProvider())


@pytest.fixture
def mock_http_response():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.aread = AsyncMock(
        return_value=json.dumps(
            {
                "issuer": "https://example.com/v1",
                "authorization_endpoint": "https://example.com/v1/authorize",
                "token_endpoint": "https://example.com/v1/token",
                "registration_endpoint": "https://example.com/v1/register",
                "response_types_supported": ["code"],
            }
        )
    )
    return mock_response


@pytest.fixture
def client_metadata():
    return ClientMetadata(
        client_name="Test Client",
        redirect_uris=[AnyHttpUrl("https://client.example.com/callback")],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )


@pytest.mark.anyio
async def test_discover_auth_metadata(auth_client, mock_http_response):
    # Mock the HTTP client's stream method
    auth_client.http_client.get = AsyncMock(return_value=mock_http_response)

    # Call the method under test
    result = await auth_client.discover_auth_metadata()

    # Assertions
    assert result is not None
    assert result.issuer == AnyHttpUrl("https://example.com/v1")
    assert result.authorization_endpoint == AnyHttpUrl(
        "https://example.com/v1/authorize"
    )
    assert result.token_endpoint == AnyHttpUrl("https://example.com/v1/token")
    assert result.registration_endpoint == AnyHttpUrl("https://example.com/v1/register")

    # Verify the correct URL was used
    expected_url = "https://example.com/.well-known/oauth-authorization-server"
    auth_client.http_client.get.assert_called_once_with(expected_url)


@pytest.mark.anyio
async def test_discover_auth_metadata_not_found(auth_client):
    # Mock 404 response
    mock_response = MagicMock()
    mock_response.status_code = 404
    auth_client.http_client.get = AsyncMock(return_value=mock_response)

    # Call the method under test
    result = await auth_client.discover_auth_metadata()

    # Assertions
    assert result is None


@pytest.mark.anyio
async def test_dynamic_client_registration(
    auth_client, client_metadata, mock_http_response
):
    # Setup mock response for registration
    registration_response = {
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "client_name": "Test Client",
        "redirect_uris": ["https://client.example.com/callback"],
        "token_endpoint_auth_method": "client_secret_post",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }
    mock_http_response.aread = AsyncMock(return_value=json.dumps(registration_response))
    auth_client.http_client.post = AsyncMock(return_value=mock_http_response)

    # Call the method under test
    registration_endpoint = "https://example.com/v1/register"
    result = await auth_client.dynamic_client_registration(
        client_metadata, registration_endpoint
    )

    # Assertions
    assert result is not None
    assert result.client_id == "test-client-id"
    assert result.client_secret == "test-client-secret"
    assert result.client_name == "Test Client"

    # Verify the request was made correctly
    auth_client.http_client.post.assert_called_once_with(
        registration_endpoint,
        json=client_metadata.model_dump(exclude_none=True),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )


@pytest.mark.anyio
async def test_dynamic_client_registration_error(auth_client, client_metadata):
    # Mock error response
    mock_error_response = AsyncMock()
    mock_error_response.__aenter__ = AsyncMock(return_value=mock_error_response)
    mock_error_response.__aexit__ = AsyncMock(return_value=None)
    mock_error_response.status_code = 400
    mock_error_response.raise_for_status = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "Client error '400 Bad Request'",
            request=MagicMock(),
            response=MagicMock(
                status_code=400,
                content=json.dumps({"error": "invalid_client_metadata"}),
            ),
        )
    )
    error_json = json.dumps({"error": "invalid_client_metadata"})
    mock_error_response.content = error_json.encode()

    auth_client.http_client.post = AsyncMock(return_value=mock_error_response)

    # Call the method under test
    registration_endpoint = "https://example.com/v1/register"
    result = await auth_client.dynamic_client_registration(
        client_metadata, registration_endpoint
    )

    # Assertions
    assert result is None


@pytest.mark.parametrize(
    "input_url,expected_discovery_url",
    [
        # Basic HTTP URL: protocol should be changed to HTTPS
        (
            "http://example.com",
            "https://example.com/.well-known/oauth-authorization-server",
        ),
        # URL with trailing slash: should be normalized
        (
            "https://example.com/",
            "https://example.com/.well-known/oauth-authorization-server",
        ),
        # URL with complex path: .well-known should be at the root
        (
            "https://example.com/api/v1/auth",
            "https://example.com/.well-known/oauth-authorization-server",
        ),
        # URL with query parameters: parameters should be ignored
        (
            "https://auth.example.org?version=2.0&debug=true",
            "https://auth.example.org/.well-known/oauth-authorization-server",
        ),
        # URL with port: port should be preserved
        (
            "http://auth.example.net:8080",
            "https://auth.example.net:8080/.well-known/oauth-authorization-server",
        ),
        # URL with subdomain, path, and trailing slash: .well-known should be at the
        # root
        (
            "http://api.auth.example.com/oauth/v2/",
            "https://api.auth.example.com/.well-known/oauth-authorization-server",
        ),
    ],
)
def test_build_discovery_url_with_various_formats(input_url, expected_discovery_url):
    # Create auth client with the given URL
    auth_client = OAuthClient(AnyHttpUrl(input_url), MockOauthClientProvider())

    # Assertions
    assert auth_client.discovery_url == AnyHttpUrl(expected_discovery_url)
