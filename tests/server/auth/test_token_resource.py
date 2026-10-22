"""Tests for RFC 8707 resource indicator handling in token exchange grants."""

import base64
import hashlib
import time

import httpx2
import pytest
from httpx2 import ASGITransport
from pydantic import AnyHttpUrl, AnyUrl
from starlette.applications import Starlette

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    IdentityAssertionParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
)
from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

pytestmark = pytest.mark.anyio

CLIENT_ID = "test-client"
CLIENT_SECRET = "test-secret"
REDIRECT_URI = "https://client.example.com/callback"
CODE_VERIFIER = "test-verifier-string-long-enough-for-pkce-verification-12345"
sha256 = hashlib.sha256(CODE_VERIFIER.encode()).digest()
CODE_CHALLENGE = base64.urlsafe_b64encode(sha256).decode().rstrip("=")


class ResourceAwareProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self) -> None:
        self.clients: dict[str, OAuthClientInformationFull] = {
            CLIENT_ID: OAuthClientInformationFull(
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                redirect_uris=[AnyUrl(REDIRECT_URI)],
                grant_types=["authorization_code", "refresh_token"],
                token_endpoint_auth_method="client_secret_post",
                scope="mcp",
            )
        }
        self.codes: dict[str, AuthorizationCode] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}
        self.access_tokens: dict[str, AccessToken] = {}
        self.last_exchange_auth_code_resource: str | None = None
        self.last_exchange_refresh_resource: str | None = None

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        pass

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        raise NotImplementedError

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return self.codes.get(authorization_code)

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
        resource: str | None = None,
    ) -> OAuthToken:
        self.last_exchange_auth_code_resource = resource
        if resource == "https://forbidden.example.com":
            raise TokenError(error="invalid_target", error_description="forbidden target resource")
        return OAuthToken(access_token="access-123", token_type="Bearer", expires_in=3600)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        return self.refresh_tokens.get(refresh_token)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
        resource: str | None = None,
    ) -> OAuthToken:
        self.last_exchange_refresh_resource = resource
        if resource == "https://forbidden.example.com":
            raise TokenError(error="invalid_target", error_description="forbidden target resource")
        return OAuthToken(access_token="access-refreshed", token_type="Bearer", expires_in=3600)

    async def load_access_token(self, token: str) -> AccessToken | None:
        return None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        pass

    async def exchange_identity_assertion(
        self, client: OAuthClientInformationFull, params: IdentityAssertionParams
    ) -> OAuthToken:
        raise NotImplementedError


class LegacyProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """Provider without resource parameter on exchange methods for backwards compatibility testing."""

    def __init__(self) -> None:
        self.clients: dict[str, OAuthClientInformationFull] = {
            CLIENT_ID: OAuthClientInformationFull(
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                redirect_uris=[AnyUrl(REDIRECT_URI)],
                grant_types=["authorization_code", "refresh_token"],
                token_endpoint_auth_method="client_secret_post",
                scope="mcp",
            )
        }
        self.codes: dict[str, AuthorizationCode] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        pass

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        raise NotImplementedError

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return self.codes.get(authorization_code)

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        return OAuthToken(access_token="legacy-access-123", token_type="Bearer", expires_in=3600)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        return self.refresh_tokens.get(refresh_token)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        return OAuthToken(access_token="legacy-refreshed", token_type="Bearer", expires_in=3600)

    async def load_access_token(self, token: str) -> AccessToken | None:
        return None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        pass

    async def exchange_identity_assertion(
        self, client: OAuthClientInformationFull, params: IdentityAssertionParams
    ) -> OAuthToken:
        raise NotImplementedError


@pytest.fixture
def provider() -> ResourceAwareProvider:
    prov = ResourceAwareProvider()
    prov.codes["code-123"] = AuthorizationCode(
        code="code-123",
        client_id=CLIENT_ID,
        scopes=["mcp"],
        expires_at=time.time() + 300,
        code_challenge=CODE_CHALLENGE,
        redirect_uri=AnyUrl(REDIRECT_URI),
        redirect_uri_provided_explicitly=True,
        resource="https://original.example.com",
    )
    prov.refresh_tokens["refresh-123"] = RefreshToken(
        token="refresh-123",
        client_id=CLIENT_ID,
        scopes=["mcp"],
        expires_at=int(time.time()) + 3600,
        resource="https://original.example.com",
    )
    return prov


@pytest.fixture
def legacy_provider() -> LegacyProvider:
    prov = LegacyProvider()
    prov.codes["code-legacy"] = AuthorizationCode(
        code="code-legacy",
        client_id=CLIENT_ID,
        scopes=["mcp"],
        expires_at=time.time() + 300,
        code_challenge=CODE_CHALLENGE,
        redirect_uri=AnyUrl(REDIRECT_URI),
        redirect_uri_provided_explicitly=True,
        resource="https://original.example.com",
    )
    prov.refresh_tokens["refresh-legacy"] = RefreshToken(
        token="refresh-legacy",
        client_id=CLIENT_ID,
        scopes=["mcp"],
        expires_at=int(time.time()) + 3600,
        resource="https://original.example.com",
    )
    return prov


@pytest.fixture
def app(provider: ResourceAwareProvider) -> Starlette:
    routes = create_auth_routes(
        provider,
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=["mcp"]),
        revocation_options=RevocationOptions(enabled=False),
    )
    return Starlette(routes=routes)


@pytest.fixture
def legacy_app(legacy_provider: LegacyProvider) -> Starlette:
    routes = create_auth_routes(
        legacy_provider,
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=["mcp"]),
        revocation_options=RevocationOptions(enabled=False),
    )
    return Starlette(routes=routes)


@pytest.fixture
async def client(app: Starlette):
    transport = ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://auth.example.com") as http:
        yield http


@pytest.fixture
async def legacy_client(legacy_app: Starlette):
    transport = ASGITransport(app=legacy_app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://auth.example.com") as http:
        yield http


async def test_authorization_code_preserves_resource_in_body(
    client: httpx2.AsyncClient, provider: ResourceAwareProvider
):
    response = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": "code-123",
            "code_verifier": CODE_VERIFIER,
            "redirect_uri": REDIRECT_URI,
            "resource": "https://requested.example.com",
        },
    )
    assert response.status_code == 200
    assert provider.last_exchange_auth_code_resource == "https://requested.example.com"


async def test_authorization_code_preserves_resource_in_query(
    client: httpx2.AsyncClient, provider: ResourceAwareProvider
):
    response = await client.post(
        "/token?resource=https://requested-query.example.com",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": "code-123",
            "code_verifier": CODE_VERIFIER,
            "redirect_uri": REDIRECT_URI,
        },
    )
    assert response.status_code == 200
    assert provider.last_exchange_auth_code_resource == "https://requested-query.example.com"


async def test_refresh_token_preserves_resource_in_body(client: httpx2.AsyncClient, provider: ResourceAwareProvider):
    response = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": "refresh-123",
            "resource": "https://refreshed.example.com",
        },
    )
    assert response.status_code == 200
    assert provider.last_exchange_refresh_resource == "https://refreshed.example.com"


async def test_refresh_token_preserves_resource_in_query(client: httpx2.AsyncClient, provider: ResourceAwareProvider):
    response = await client.post(
        "/token?resource=https://refreshed-query.example.com",
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": "refresh-123",
        },
    )
    assert response.status_code == 200
    assert provider.last_exchange_refresh_resource == "https://refreshed-query.example.com"


async def test_provider_rejects_mismatched_resource_with_invalid_target(
    client: httpx2.AsyncClient, provider: ResourceAwareProvider
):
    response = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": "refresh-123",
            "resource": "https://forbidden.example.com",
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "invalid_target"
    assert data["error_description"] == "forbidden target resource"


async def test_legacy_provider_without_resource_parameter_supported(
    legacy_client: httpx2.AsyncClient, legacy_provider: LegacyProvider
):
    response = await legacy_client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": "code-legacy",
            "code_verifier": CODE_VERIFIER,
            "redirect_uri": REDIRECT_URI,
            "resource": "https://requested.example.com",
        },
    )
    assert response.status_code == 200

    response = await legacy_client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": "refresh-legacy",
            "resource": "https://refreshed.example.com",
        },
    )
    assert response.status_code == 200
