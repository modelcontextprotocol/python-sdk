import urllib.parse
import warnings

import jwt
import pytest
from pydantic import AnyHttpUrl, AnyUrl

from mcp.client.auth.extensions.client_credentials import (
    ClientCredentialsOAuthProvider,
    JWTParameters,
    PrivateKeyJWTOAuthProvider,
    RFC7523OAuthClientProvider,
    SignedJWTParameters,
    static_assertion_provider,
)
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)
from mcp.shared.exceptions import MCPDeprecationWarning


class MockTokenStorage:
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
    async def redirect_handler(url: str) -> None:  # pragma: no cover
        pass

    async def callback_handler() -> AuthorizationCodeResult:  # pragma: no cover
        return AuthorizationCodeResult(code="test_auth_code", state="test_state")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", MCPDeprecationWarning)
        return RFC7523OAuthClientProvider(
            server_url="https://api.example.com/v1/mcp",
            client_metadata=client_metadata,
            storage=mock_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )


class TestOAuthFlowClientCredentials:
    @pytest.mark.anyio
    async def test_token_exchange_request_jwt_predefined(self, rfc7523_oauth_provider: RFC7523OAuthClientProvider):
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

        content = urllib.parse.unquote_plus(request.content.decode()).split("&")
        assert "grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer" in content
        assert "scope=read write" in content
        assert "resource=https://api.example.com/v1/mcp" in content

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


class TestClientCredentialsOAuthProvider:
    @pytest.mark.anyio
    async def test_init_sets_client_info(self, mock_storage: MockTokenStorage):
        provider = ClientCredentialsOAuthProvider(
            server_url="https://api.example.com",
            storage=mock_storage,
            client_id="test-client-id",
            client_secret="test-client-secret",
        )

        await provider._initialize()

        assert provider.context.client_info is not None
        assert provider.context.client_info.client_id == "test-client-id"
        assert provider.context.client_info.client_secret == "test-client-secret"
        assert provider.context.client_info.grant_types == ["client_credentials"]
        assert provider.context.client_info.token_endpoint_auth_method == "client_secret_basic"

    @pytest.mark.anyio
    async def test_init_with_scopes(self, mock_storage: MockTokenStorage):
        provider = ClientCredentialsOAuthProvider(
            server_url="https://api.example.com",
            storage=mock_storage,
            client_id="test-client-id",
            client_secret="test-client-secret",
            scopes="read write",
        )

        await provider._initialize()
        assert provider.context.client_info is not None
        assert provider.context.client_info.scope == "read write"

    @pytest.mark.anyio
    async def test_init_with_client_secret_post(self, mock_storage: MockTokenStorage):
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
        provider = ClientCredentialsOAuthProvider(
            server_url="https://api.example.com/v1/mcp",
            storage=mock_storage,
            client_id="test-client-id",
            client_secret="test-client-secret",
            scopes="read write",
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
            scopes="read write",
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
        assert "Authorization" not in request.headers

    @pytest.mark.anyio
    async def test_exchange_token_client_secret_post_without_client_id(self, mock_storage: MockTokenStorage):
        provider = ClientCredentialsOAuthProvider(
            server_url="https://api.example.com/v1/mcp",
            storage=mock_storage,
            client_id="placeholder",
            client_secret="test-client-secret",
            token_endpoint_auth_method="client_secret_post",
            scopes="read write",
        )
        await provider._initialize()
        provider.context.oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://api.example.com"),
            authorization_endpoint=AnyHttpUrl("https://api.example.com/authorize"),
            token_endpoint=AnyHttpUrl("https://api.example.com/token"),
        )
        provider.context.protocol_version = "2025-06-18"
        # Replace the client_info set by _initialize to hit the client_id=None edge case
        provider.context.client_info = OAuthClientInformationFull(
            redirect_uris=None,
            client_id=None,
            client_secret="test-client-secret",
            grant_types=["client_credentials"],
            token_endpoint_auth_method="client_secret_post",
            scope="read write",
        )

        request = await provider._perform_authorization()

        content = urllib.parse.unquote_plus(request.content.decode())
        assert "grant_type=client_credentials" in content
        # RFC 6749 §2.3.1 requires both credentials for client_secret_post, so neither is sent
        assert "client_id=" not in content
        assert "client_secret=" not in content
        assert "Authorization" not in request.headers

    @pytest.mark.anyio
    async def test_exchange_token_without_scopes(self, mock_storage: MockTokenStorage):
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
    @pytest.mark.anyio
    async def test_init_sets_client_info(self, mock_storage: MockTokenStorage):
        async def mock_assertion_provider(audience: str) -> str:  # pragma: no cover
            return "mock-jwt"

        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com",
            storage=mock_storage,
            client_id="test-client-id",
            assertion_provider=mock_assertion_provider,
        )

        await provider._initialize()

        assert provider.context.client_info is not None
        assert provider.context.client_info.client_id == "test-client-id"
        assert provider.context.client_info.grant_types == ["client_credentials"]
        assert provider.context.client_info.token_endpoint_auth_method == "private_key_jwt"

    @pytest.mark.anyio
    async def test_exchange_token_client_credentials(self, mock_storage: MockTokenStorage):
        async def mock_assertion_provider(audience: str) -> str:
            return f"jwt-for-{audience}"

        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com/v1/mcp",
            storage=mock_storage,
            client_id="test-client-id",
            assertion_provider=mock_assertion_provider,
            scopes="read write",
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
    @pytest.mark.anyio
    async def test_create_assertion_provider(self):
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
    @pytest.mark.anyio
    async def test_returns_static_token(self):
        token = "my-static-jwt-token"
        provider = static_assertion_provider(token)

        result1 = await provider("https://auth1.example.com")
        result2 = await provider("https://auth2.example.com")

        assert result1 == token
        assert result2 == token
