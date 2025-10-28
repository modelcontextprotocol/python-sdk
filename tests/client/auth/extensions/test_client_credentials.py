import urllib.parse

import jwt
import pytest
from pydantic import AnyHttpUrl, AnyUrl

from mcp.client.auth.extensions.client_credentials import JWTParameters, RFC7523OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthMetadata, OAuthToken


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
def rfc7523_oauth_provider(client_metadata: OAuthClientMetadata, mock_storage: MockTokenStorage):
    async def redirect_handler(url: str) -> None:
        """Mock redirect handler."""
        pass

    async def callback_handler() -> tuple[str, str | None]:
        """Mock callback handler."""
        return "test_auth_code", "test_state"

    return RFC7523OAuthClientProvider(
        server_url="https://api.example.com/v1/mcp",
        client_metadata=client_metadata,
        storage=mock_storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


class TestOAuthFlowClientCredentials:
    """Test OAuth flow behavior for client credentials flows."""

    @pytest.mark.anyio
    async def test_token_exchange_request_jwt_predefined(self, rfc7523_oauth_provider: RFC7523OAuthClientProvider):
        """Test token exchange request building with a predefined JWT assertion."""
        # Set up required context
        rfc7523_oauth_provider.context.client_info = OAuthClientInformationFull(
            grant_types=["urn:ietf:params:oauth:grant-type:jwt-bearer"],
            token_endpoint_auth_method="private_key_jwt",
            redirect_uris=None,
            scope="read write",
        )
        rfc7523_oauth_provider.context.oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://api.example.com"),
            authorization_endpoint=AnyHttpUrl("https://api.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://api.example.com/token"),
            registration_endpoint=AnyHttpUrl("https://api.example.com/register"),
        )
        rfc7523_oauth_provider.context.client_metadata = rfc7523_oauth_provider.context.client_info
        rfc7523_oauth_provider.context.protocol_version = "2025-06-18"
        rfc7523_oauth_provider.jwt_parameters = JWTParameters(
            # https://www.jwt.io
            assertion="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiYWRtaW4iOnRydWUsImlhdCI6MTUxNjIzOTAyMn0.KMUFsIDTnFmyG3nMiGM6H9FNFUROf3wh7SmqJp-QV30"
        )

        request = await rfc7523_oauth_provider._exchange_token_jwt_bearer()

        assert request.method == "POST"
        assert str(request.url) == "https://api.example.com/token"
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"

        # Check form data
        content = urllib.parse.unquote_plus(request.content.decode())
        assert "grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer" in content
        assert "scope=read write" in content
        assert "resource=https://api.example.com/v1/mcp" in content
        assert (
            "assertion=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiYWRtaW4iOnRydWUsImlhdCI6MTUxNjIzOTAyMn0.KMUFsIDTnFmyG3nMiGM6H9FNFUROf3wh7SmqJp-QV30"
            in content
        )

    @pytest.mark.anyio
    async def test_token_exchange_request_jwt(self, rfc7523_oauth_provider: RFC7523OAuthClientProvider):
        """Test token exchange request building wiith a generated JWT assertion."""
        # Set up required context
        rfc7523_oauth_provider.context.client_info = OAuthClientInformationFull(
            grant_types=["urn:ietf:params:oauth:grant-type:jwt-bearer"],
            token_endpoint_auth_method="private_key_jwt",
            redirect_uris=None,
            scope="read write",
        )
        rfc7523_oauth_provider.context.oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://api.example.com"),
            authorization_endpoint=AnyHttpUrl("https://api.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://api.example.com/token"),
            registration_endpoint=AnyHttpUrl("https://api.example.com/register"),
        )
        rfc7523_oauth_provider.context.client_metadata = rfc7523_oauth_provider.context.client_info
        rfc7523_oauth_provider.context.protocol_version = "2025-06-18"
        rfc7523_oauth_provider.jwt_parameters = JWTParameters(
            issuer="foo",
            subject="1234567890",
            claims={
                "name": "John Doe",
                "admin": True,
                "iat": 1516239022,
            },
            jwt_signing_algorithm="HS256",
            jwt_signing_key="a-string-secret-at-least-256-bits-long",
            jwt_lifetime_seconds=300,
        )

        request = await rfc7523_oauth_provider._exchange_token_jwt_bearer()

        assert request.method == "POST"
        assert str(request.url) == "https://api.example.com/token"
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"

        # Check form data
        content = urllib.parse.unquote_plus(request.content.decode()).split("&")
        assert "grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer" in content
        assert "scope=read write" in content
        assert "resource=https://api.example.com/v1/mcp" in content

        # Check assertion
        assertion = next(param for param in content if param.startswith("assertion="))[len("assertion=") :]
        claims = jwt.decode(
            assertion,
            key="a-string-secret-at-least-256-bits-long",
            algorithms=["HS256"],
            audience="https://api.example.com/",
            subject="1234567890",
            issuer="foo",
            verify=True,
        )
        assert claims["name"] == "John Doe"
        assert claims["admin"]
        assert claims["iat"] == 1516239022
