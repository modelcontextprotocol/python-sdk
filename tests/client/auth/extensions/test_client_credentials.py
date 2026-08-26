import urllib.parse
from collections.abc import AsyncGenerator

import httpx2
import jwt
import pytest
from inline_snapshot import snapshot
from pydantic import AnyHttpUrl

from mcp.client.auth import OAuthClientProvider, OAuthFlowError
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

    async def set_tokens(self, tokens: OAuthToken) -> None:
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


_SERVER_URL = "https://api.example.com/v1/mcp"
_CONFIGURED_ISSUER = "https://auth.example.com"


def _metadata_for(issuer: str) -> dict[str, str]:
    return {"issuer": issuer, "authorization_endpoint": f"{issuer}/authorize", "token_endpoint": f"{issuer}/token"}


def _provider_with_issuer(kind: str, storage: MockTokenStorage, audiences: list[str]) -> OAuthClientProvider:
    """A ClientCredentials ("secret") or PrivateKeyJWT ("jwt") provider configured for _CONFIGURED_ISSUER;
    `audiences` records every audience an assertion is minted for."""
    if kind == "secret":
        return ClientCredentialsOAuthProvider(
            server_url=_SERVER_URL, storage=storage, client_id="cid", client_secret="csecret", issuer=_CONFIGURED_ISSUER
        )

    async def assertion_provider(audience: str) -> str:
        audiences.append(audience)
        return "signed-assertion"

    return PrivateKeyJWTOAuthProvider(
        server_url=_SERVER_URL,
        storage=storage,
        client_id="cid",
        assertion_provider=assertion_provider,
        issuer=_CONFIGURED_ISSUER,
    )


async def _answer_discovery(
    flow: AsyncGenerator[httpx2.Request, httpx2.Response],
    *,
    authorization_server: str | list[str] | None,
    metadata: dict[str, str] | None,
) -> httpx2.Request:
    """Answer the provider's first request with a 401 and its discovery requests as described;
    return the request it builds once discovery is over.

    `authorization_server` is what protected-resource metadata advertises (None: no PRM is
    served); `metadata` is the authorization server metadata document (None: every well-known
    404s).
    """
    request = await flow.__anext__()
    request = await flow.asend(httpx2.Response(401, request=request))
    while "/.well-known/oauth-protected-resource" in str(request.url):
        if authorization_server is None:
            response = httpx2.Response(404, request=request)
        else:
            advertised = authorization_server if isinstance(authorization_server, list) else [authorization_server]
            prm = {"resource": _SERVER_URL, "authorization_servers": advertised}
            response = httpx2.Response(200, json=prm, request=request)
        request = await flow.asend(response)
    while "/.well-known/" in str(request.url):
        if metadata is None:
            response = httpx2.Response(404, request=request)
        else:
            response = httpx2.Response(200, json=metadata, request=request)
        request = await flow.asend(response)
    return request


@pytest.mark.anyio
@pytest.mark.parametrize(
    "served_issuer", [_CONFIGURED_ISSUER, f"{_CONFIGURED_ISSUER}/"], ids=["as-configured", "root-slash"]
)
@pytest.mark.parametrize("kind", ["secret", "jwt"])
async def test_provider_with_configured_issuer_exchanges_at_that_issuer(
    mock_storage: MockTokenStorage, kind: str, served_issuer: str
):
    """SDK-defined: with `issuer=` set and metadata discovered for that issuer (a root issuer served with
    its trailing slash is the same server), the token request goes to its token endpoint (positive
    control for the refusals below)."""
    audiences: list[str] = []
    provider = _provider_with_issuer(kind, mock_storage, audiences)
    flow = provider.async_auth_flow(httpx2.Request("POST", _SERVER_URL))
    metadata = {**_metadata_for(_CONFIGURED_ISSUER), "issuer": served_issuer}

    token_request = await _answer_discovery(flow, authorization_server=served_issuer, metadata=metadata)

    assert (token_request.method, str(token_request.url)) == ("POST", "https://auth.example.com/token")
    assert audiences == ([] if kind == "secret" else [served_issuer])
    await flow.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["secret", "jwt"])
async def test_provider_picks_its_configured_issuer_among_several_advertised_servers(
    mock_storage: MockTokenStorage, kind: str
):
    """SDK-defined: when the resource lists several authorization servers, the one matching `issuer=` is
    discovered and used even if it is not listed first."""
    provider = _provider_with_issuer(kind, mock_storage, [])
    flow = provider.async_auth_flow(httpx2.Request("POST", _SERVER_URL))

    token_request = await _answer_discovery(
        flow,
        authorization_server=["https://other-as.example.com", _CONFIGURED_ISSUER],
        metadata=_metadata_for(_CONFIGURED_ISSUER),
    )

    assert provider.context.auth_server_url == _CONFIGURED_ISSUER
    assert str(token_request.url) == "https://auth.example.com/token"
    await flow.aclose()


def test_an_issuer_that_is_not_an_http_url_is_rejected_at_construction(mock_storage: MockTokenStorage) -> None:
    """SDK-defined: `issuer=` is the authorization server's issuer URL; anything else is a configuration
    error on both machine-to-machine providers."""
    with pytest.raises(ValueError) as cc_error:
        ClientCredentialsOAuthProvider(
            server_url=_SERVER_URL, storage=mock_storage, client_id="cid", client_secret="s", issuer="auth.example.com"
        )
    with pytest.raises(ValueError) as jwt_error:
        PrivateKeyJWTOAuthProvider(
            server_url=_SERVER_URL,
            storage=mock_storage,
            client_id="cid",
            assertion_provider=static_assertion_provider("jwt"),
            issuer="auth.example.com",
        )
    assert (
        str(cc_error.value)
        == str(jwt_error.value)
        == snapshot("issuer must be the authorization server's http(s) issuer URL, got 'auth.example.com'")
    )


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["secret", "jwt"])
async def test_provider_refuses_metadata_for_a_different_issuer(mock_storage: MockTokenStorage, kind: str):
    """SDK-defined: when discovery ends at an authorization server other than the configured `issuer`,
    no token request is built and no assertion is minted."""
    audiences: list[str] = []
    provider = _provider_with_issuer(kind, mock_storage, audiences)
    flow = provider.async_auth_flow(httpx2.Request("POST", _SERVER_URL))

    with pytest.raises(OAuthFlowError) as exc_info:
        await _answer_discovery(
            flow,
            authorization_server="https://other-as.example.com",
            metadata=_metadata_for("https://other-as.example.com"),
        )

    assert str(exc_info.value) == snapshot(
        "Authorization server metadata issuer mismatch: https://other-as.example.com != https://auth.example.com"
    )
    assert audiences == []


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["secret", "jwt"])
async def test_provider_refuses_to_exchange_without_metadata_when_issuer_configured(
    mock_storage: MockTokenStorage, kind: str
):
    """SDK-defined: with `issuer=` set, the 2025-03-26 default `/token` on the resource origin is not
    used when no authorization server metadata could be discovered."""
    audiences: list[str] = []
    provider = _provider_with_issuer(kind, mock_storage, audiences)
    flow = provider.async_auth_flow(httpx2.Request("POST", _SERVER_URL))

    with pytest.raises(OAuthFlowError) as exc_info:
        await _answer_discovery(flow, authorization_server=None, metadata=None)

    assert str(exc_info.value) == snapshot(
        "No authorization server metadata discovered for configured issuer https://auth.example.com"
    )
    assert audiences == []


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["secret", "jwt"])
async def test_a_refused_authorization_server_is_forgotten_so_the_next_request_rediscovers(
    mock_storage: MockTokenStorage, kind: str
):
    """SDK-defined: when the exchange is refused because discovery ended somewhere other than the
    configured issuer, the refused metadata and any token held are dropped; the next request goes out
    unauthenticated and discovery starts again, rather than a refresh being built from what was refused."""
    provider = _provider_with_issuer(kind, mock_storage, [])
    flow = provider.async_auth_flow(httpx2.Request("POST", _SERVER_URL))
    token_request = await _answer_discovery(
        flow, authorization_server=_CONFIGURED_ISSUER, metadata=_metadata_for(_CONFIGURED_ISSUER)
    )
    token = {"access_token": "first", "token_type": "Bearer", "expires_in": 3600, "refresh_token": "rt"}
    retried = await flow.asend(httpx2.Response(200, json=token, request=token_request))
    with pytest.raises(StopAsyncIteration):
        await flow.asend(httpx2.Response(200, request=retried))

    flow = provider.async_auth_flow(httpx2.Request("POST", _SERVER_URL))
    with pytest.raises(OAuthFlowError):
        await _answer_discovery(
            flow,
            authorization_server="https://other-as.example.com",
            metadata=_metadata_for("https://other-as.example.com"),
        )
    assert provider.context.oauth_metadata is None
    assert provider.context.current_tokens is None

    flow = provider.async_auth_flow(httpx2.Request("POST", _SERVER_URL))
    request = await flow.__anext__()
    assert (str(request.url), request.headers.get("Authorization")) == (_SERVER_URL, None)
    await flow.aclose()
