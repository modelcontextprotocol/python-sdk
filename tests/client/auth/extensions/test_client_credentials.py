import urllib.parse

import jwt
import pytest
from pydantic import AnyHttpUrl

from mcp.client.auth.extensions.client_credentials import (
    ClientCredentialsOAuthProvider,
    PrivateKeyJWTOAuthProvider,
    SignedJWTParameters,
    static_assertion_provider,
)
from mcp.shared.auth import (
    OAuthClientInformationFull,
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

    async def set_tokens(self, tokens: OAuthToken) -> None:  # pragma: no cover
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:  # pragma: no cover
        return self._client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:  # pragma: no cover
        self._client_info = client_info


@pytest.fixture
def mock_storage():
    return MockTokenStorage()


class TestClientCredentialsOAuthProvider:
    """Test ClientCredentialsOAuthProvider."""

    @pytest.mark.anyio
    async def test_init_sets_client_info(self, mock_storage: MockTokenStorage):
        """Test that _initialize sets client_info."""
        provider = ClientCredentialsOAuthProvider(
            server_url="https://api.example.com",
            storage=mock_storage,
            client_id="test-client-id",
            client_secret="test-client-secret",
        )

        # client_info is set during _initialize
        await provider._initialize()

        assert provider.context.client_info is not None
        assert provider.context.client_info.client_id == "test-client-id"
        assert provider.context.client_info.client_secret == "test-client-secret"
        assert provider.context.client_info.grant_types == ["client_credentials"]
        assert provider.context.client_info.token_endpoint_auth_method == "client_secret_basic"

    @pytest.mark.anyio
    async def test_init_with_scopes(self, mock_storage: MockTokenStorage):
        """Test that constructor accepts scopes."""
        provider = ClientCredentialsOAuthProvider(
            server_url="https://api.example.com",
            storage=mock_storage,
            client_id="test-client-id",
            client_secret="test-client-secret",
            scope="read write",
        )

        await provider._initialize()
        assert provider.context.client_info is not None
        assert provider.context.client_info.scope == "read write"

    @pytest.mark.anyio
    async def test_init_with_client_secret_post(self, mock_storage: MockTokenStorage):
        """Test that constructor accepts client_secret_post auth method."""
        provider = ClientCredentialsOAuthProvider(
            server_url="https://api.example.com",
            storage=mock_storage,
            client_id="test-client-id",
            client_secret="test-client-secret",
            token_endpoint_auth_method="client_secret_post",
        )

        await provider._initialize()
        assert provider.context.client_info is not None
        assert provider.context.client_info.token_endpoint_auth_method == "client_secret_post"

    @pytest.mark.anyio
    async def test_exchange_token_client_credentials(self, mock_storage: MockTokenStorage):
        """Test token exchange request building."""
        provider = ClientCredentialsOAuthProvider(
            server_url="https://api.example.com/v1/mcp",
            storage=mock_storage,
            client_id="test-client-id",
            client_secret="test-client-secret",
            scope="read write",
        )
        provider.context.oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://api.example.com"),
            authorization_endpoint=AnyHttpUrl("https://api.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://api.example.com/token"),
        )
        provider.context.protocol_version = "2025-06-18"

        request = await provider._perform_authorization()

        assert request.method == "POST"
        assert str(request.url) == "https://api.example.com/token"

        content = urllib.parse.unquote_plus(request.content.decode())
        assert "grant_type=client_credentials" in content
        assert "scope=read write" in content
        assert "resource=https://api.example.com/v1/mcp" in content

    @pytest.mark.anyio
    async def test_exchange_token_client_secret_post_includes_client_id(self, mock_storage: MockTokenStorage):
        """Test that client_secret_post includes both client_id and client_secret in body (RFC 6749 §2.3.1)."""
        provider = ClientCredentialsOAuthProvider(
            server_url="https://api.example.com/v1/mcp",
            storage=mock_storage,
            client_id="test-client-id",
            client_secret="test-client-secret",
            token_endpoint_auth_method="client_secret_post",
            scope="read write",
        )
        await provider._initialize()
        provider.context.oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://api.example.com"),
            authorization_endpoint=AnyHttpUrl("https://api.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://api.example.com/token"),
        )
        provider.context.protocol_version = "2025-06-18"

        request = await provider._perform_authorization()

        content = urllib.parse.unquote_plus(request.content.decode())
        assert "grant_type=client_credentials" in content
        assert "client_id=test-client-id" in content
        assert "client_secret=test-client-secret" in content
        # Should NOT have Basic auth header
        assert "Authorization" not in request.headers

    @pytest.mark.anyio
    async def test_exchange_token_without_scopes(self, mock_storage: MockTokenStorage):
        """Test token exchange without scopes."""
        provider = ClientCredentialsOAuthProvider(
            server_url="https://api.example.com/v1/mcp",
            storage=mock_storage,
            client_id="test-client-id",
            client_secret="test-client-secret",
        )
        provider.context.oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://api.example.com"),
            authorization_endpoint=AnyHttpUrl("https://api.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://api.example.com/token"),
        )
        provider.context.protocol_version = "2024-11-05"  # Old version - no resource param

        request = await provider._perform_authorization()

        content = urllib.parse.unquote_plus(request.content.decode())
        assert "grant_type=client_credentials" in content
        assert "scope=" not in content
        assert "resource=" not in content


class TestPrivateKeyJWTOAuthProvider:
    """Test PrivateKeyJWTOAuthProvider."""

    @pytest.mark.anyio
    async def test_init_sets_client_info(self, mock_storage: MockTokenStorage):
        """Test that _initialize sets client_info."""

        async def mock_assertion_provider(audience: str) -> str:  # pragma: no cover
            return "mock-jwt"

        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com",
            storage=mock_storage,
            client_id="test-client-id",
            assertion_provider=mock_assertion_provider,
        )

        # client_info is set during _initialize
        await provider._initialize()

        assert provider.context.client_info is not None
        assert provider.context.client_info.client_id == "test-client-id"
        assert provider.context.client_info.grant_types == ["client_credentials"]
        assert provider.context.client_info.token_endpoint_auth_method == "private_key_jwt"

    @pytest.mark.anyio
    async def test_exchange_token_client_credentials(self, mock_storage: MockTokenStorage):
        """Test token exchange request building with assertion provider."""

        async def mock_assertion_provider(audience: str) -> str:
            return f"jwt-for-{audience}"

        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com/v1/mcp",
            storage=mock_storage,
            client_id="test-client-id",
            assertion_provider=mock_assertion_provider,
            scope="read write",
        )
        provider.context.oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://auth.example.com"),
            authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
        )
        provider.context.protocol_version = "2025-06-18"

        request = await provider._perform_authorization()

        assert request.method == "POST"
        assert str(request.url) == "https://auth.example.com/token"

        content = urllib.parse.unquote_plus(request.content.decode())
        assert "grant_type=client_credentials" in content
        assert "client_assertion=jwt-for-https://auth.example.com/" in content
        assert "client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer" in content
        assert "scope=read write" in content

    @pytest.mark.anyio
    async def test_exchange_token_without_scopes(self, mock_storage: MockTokenStorage):
        """Test token exchange without scopes."""

        async def mock_assertion_provider(audience: str) -> str:
            return f"jwt-for-{audience}"

        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com/v1/mcp",
            storage=mock_storage,
            client_id="test-client-id",
            assertion_provider=mock_assertion_provider,
        )
        provider.context.oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://auth.example.com"),
            authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
        )
        provider.context.protocol_version = "2024-11-05"  # Old version - no resource param

        request = await provider._perform_authorization()

        content = urllib.parse.unquote_plus(request.content.decode())
        assert "grant_type=client_credentials" in content
        assert "scope=" not in content
        assert "resource=" not in content


class TestSignedJWTParameters:
    """Test SignedJWTParameters."""

    @pytest.mark.anyio
    async def test_create_assertion_provider(self):
        """Test that create_assertion_provider creates valid JWTs."""
        params = SignedJWTParameters(
            issuer="test-issuer",
            subject="test-subject",
            signing_key="a-string-secret-at-least-256-bits-long",
            signing_algorithm="HS256",
            lifetime_seconds=300,
        )

        provider = params.create_assertion_provider()
        assertion = await provider("https://auth.example.com")

        claims = jwt.decode(
            assertion,
            key="a-string-secret-at-least-256-bits-long",
            algorithms=["HS256"],
            audience="https://auth.example.com",
        )
        assert claims["iss"] == "test-issuer"
        assert claims["sub"] == "test-subject"
        assert claims["aud"] == "https://auth.example.com"
        assert "exp" in claims
        assert "iat" in claims
        assert "jti" in claims

    @pytest.mark.anyio
    async def test_create_assertion_provider_with_additional_claims(self):
        """Test that additional_claims are included in the JWT."""
        params = SignedJWTParameters(
            issuer="test-issuer",
            subject="test-subject",
            signing_key="a-string-secret-at-least-256-bits-long",
            signing_algorithm="HS256",
            additional_claims={"custom": "value"},
        )

        provider = params.create_assertion_provider()
        assertion = await provider("https://auth.example.com")

        claims = jwt.decode(
            assertion,
            key="a-string-secret-at-least-256-bits-long",
            algorithms=["HS256"],
            audience="https://auth.example.com",
        )
        assert claims["custom"] == "value"


class TestStaticAssertionProvider:
    """Test static_assertion_provider helper."""

    @pytest.mark.anyio
    async def test_returns_static_token(self):
        """Test that static_assertion_provider returns the same token regardless of audience."""
        token = "my-static-jwt-token"
        provider = static_assertion_provider(token)

        result1 = await provider("https://auth1.example.com")
        result2 = await provider("https://auth2.example.com")

        assert result1 == token
        assert result2 == token
