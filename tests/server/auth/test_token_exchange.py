"""Server-side RFC 8693 token-exchange handling (SEP-990 enterprise IdP flows)."""

import secrets
import time

import httpx
import pytest
from httpx import ASGITransport
from pydantic import AnyHttpUrl
from starlette.applications import Starlette

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    TokenExchangeParams,
)
from mcp.server.auth.routes import build_metadata, create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken, TokenExchangeToken

TOKEN_EXCHANGE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
VALID_SUBJECT_TOKEN = "valid-id-jag"


class TokenExchangeProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """A provider that implements `exchange_token`; everything else is unused here."""

    def __init__(self) -> None:
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.tokens: dict[str, AccessToken] = {}
        self.last_params: TokenExchangeParams | None = None

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        assert client_info.client_id is not None
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        raise NotImplementedError

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        raise NotImplementedError

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        raise NotImplementedError

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        raise NotImplementedError

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        raise NotImplementedError

    async def load_access_token(self, token: str) -> AccessToken | None:
        return self.tokens.get(token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        raise NotImplementedError

    async def exchange_token(self, client: OAuthClientInformationFull, params: TokenExchangeParams) -> OAuthToken:
        self.last_params = params
        if params.subject_token != VALID_SUBJECT_TOKEN:
            raise TokenError(error="invalid_grant", error_description="subject token is not valid")
        if params.resource == "https://unknown.example.com":
            raise TokenError(error="invalid_target", error_description="unknown resource")
        assert client.client_id is not None
        scopes = params.scopes or ["mcp"]
        access = f"access_{secrets.token_hex(16)}"
        self.tokens[access] = AccessToken(
            token=access,
            client_id=client.client_id,
            scopes=scopes,
            expires_at=int(time.time()) + 3600,
            resource=params.resource,
            subject="exchanged-user",
        )
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=3600, scope=" ".join(scopes))


@pytest.fixture
def provider() -> TokenExchangeProvider:
    return TokenExchangeProvider()


@pytest.fixture
def app(provider: TokenExchangeProvider) -> Starlette:
    routes = create_auth_routes(
        provider,
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=["mcp"]),
        revocation_options=RevocationOptions(enabled=False),
        token_exchange_enabled=True,
    )
    return Starlette(routes=routes)


@pytest.fixture
async def client(app: Starlette):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://auth.example.com") as http:
        yield http


async def register(http: httpx.AsyncClient) -> dict[str, str]:
    # The DCR handler requires `authorization_code`; a token-exchange client registers both.
    response = await http.post(
        "/register",
        json={
            "redirect_uris": ["https://client.example.com/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "grant_types": ["authorization_code", TOKEN_EXCHANGE_GRANT_TYPE],
            "response_types": ["code"],
        },
    )
    assert response.status_code == 201, response.content
    return response.json()


def test_build_metadata_advertises_token_exchange_when_enabled():
    enabled = build_metadata(
        AnyHttpUrl("https://auth.example.com"),
        None,
        ClientRegistrationOptions(),
        RevocationOptions(),
        supports_token_exchange=True,
    )
    assert TOKEN_EXCHANGE_GRANT_TYPE in (enabled.grant_types_supported or [])

    disabled = build_metadata(
        AnyHttpUrl("https://auth.example.com"),
        None,
        ClientRegistrationOptions(),
        RevocationOptions(),
    )
    assert TOKEN_EXCHANGE_GRANT_TYPE not in (disabled.grant_types_supported or [])


def test_build_metadata_advertises_none_auth_method_when_enabled():
    enabled = build_metadata(
        AnyHttpUrl("https://auth.example.com"),
        None,
        ClientRegistrationOptions(),
        RevocationOptions(),
        supports_token_exchange=True,
    )
    assert "none" in (enabled.token_endpoint_auth_methods_supported or [])

    disabled = build_metadata(
        AnyHttpUrl("https://auth.example.com"),
        None,
        ClientRegistrationOptions(),
        RevocationOptions(),
    )
    assert "none" not in (disabled.token_endpoint_auth_methods_supported or [])


@pytest.mark.anyio
async def test_metadata_endpoint_lists_token_exchange(client: httpx.AsyncClient):
    response = await client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    body = response.json()
    assert TOKEN_EXCHANGE_GRANT_TYPE in body["grant_types_supported"]
    assert "none" in body["token_endpoint_auth_methods_supported"]


@pytest.mark.anyio
async def test_token_exchange_success(client: httpx.AsyncClient, provider: TokenExchangeProvider):
    client_info = await register(client)

    response = await client.post(
        "/token",
        data={
            "grant_type": TOKEN_EXCHANGE_GRANT_TYPE,
            "client_id": client_info["client_id"],
            "client_secret": client_info["client_secret"],
            "subject_token": VALID_SUBJECT_TOKEN,
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "scope": "mcp",
            "resource": "https://mcp.example.com/mcp",
        },
    )

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["token_type"] == "Bearer"
    # RFC 8693 §2.2.1: the response identifies the issued token type. The provider returned a
    # plain OAuthToken, so the handler defaulted it to the access-token type.
    assert body["issued_token_type"] == "urn:ietf:params:oauth:token-type:access_token"
    assert response.headers["cache-control"] == "no-store"

    # The issued token is valid for the resource server to load.
    issued = await provider.load_access_token(body["access_token"])
    assert issued is not None
    assert issued.scopes == ["mcp"]
    assert issued.subject == "exchanged-user"

    assert provider.last_params is not None
    assert provider.last_params.subject_token == VALID_SUBJECT_TOKEN
    assert provider.last_params.subject_token_type == "urn:ietf:params:oauth:token-type:jwt"
    assert provider.last_params.scopes == ["mcp"]
    assert provider.last_params.resource == "https://mcp.example.com/mcp"


@pytest.mark.anyio
async def test_token_exchange_provider_sets_issued_token_type():
    """A provider returning a TokenExchangeToken controls the issued_token_type verbatim."""

    class CustomIssuedTypeProvider(TokenExchangeProvider):
        async def exchange_token(self, client: OAuthClientInformationFull, params: TokenExchangeParams) -> OAuthToken:
            return TokenExchangeToken(
                access_token="custom",
                token_type="Bearer",
                expires_in=3600,
                issued_token_type="urn:ietf:params:oauth:token-type:jwt",
            )

    provider = CustomIssuedTypeProvider()
    routes = create_auth_routes(
        provider,
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=["mcp"]),
        revocation_options=RevocationOptions(enabled=False),
        token_exchange_enabled=True,
    )
    app = Starlette(routes=routes)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://auth.example.com") as http:
        client_info = await register(http)
        response = await http.post(
            "/token",
            data={
                "grant_type": TOKEN_EXCHANGE_GRANT_TYPE,
                "client_id": client_info["client_id"],
                "client_secret": client_info["client_secret"],
                "subject_token": VALID_SUBJECT_TOKEN,
                "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            },
        )

    assert response.status_code == 200, response.content
    assert response.json()["issued_token_type"] == "urn:ietf:params:oauth:token-type:jwt"


@pytest.mark.anyio
async def test_token_exchange_invalid_subject_token(client: httpx.AsyncClient):
    client_info = await register(client)

    response = await client.post(
        "/token",
        data={
            "grant_type": TOKEN_EXCHANGE_GRANT_TYPE,
            "client_id": client_info["client_id"],
            "client_secret": client_info["client_secret"],
            "subject_token": "forged",
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_grant", "error_description": "subject token is not valid"}


@pytest.mark.anyio
async def test_token_exchange_invalid_target(client: httpx.AsyncClient):
    client_info = await register(client)

    response = await client.post(
        "/token",
        data={
            "grant_type": TOKEN_EXCHANGE_GRANT_TYPE,
            "client_id": client_info["client_id"],
            "client_secret": client_info["client_secret"],
            "subject_token": VALID_SUBJECT_TOKEN,
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "resource": "https://unknown.example.com",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_target", "error_description": "unknown resource"}


@pytest.mark.anyio
async def test_token_exchange_with_client_secret_basic(client: httpx.AsyncClient, provider: TokenExchangeProvider):
    """A confidential client may authenticate with HTTP Basic auth (client_id still in the body)."""
    response = await client.post(
        "/register",
        json={
            "redirect_uris": ["https://client.example.com/callback"],
            "token_endpoint_auth_method": "client_secret_basic",
            "grant_types": ["authorization_code", TOKEN_EXCHANGE_GRANT_TYPE],
            "response_types": ["code"],
        },
    )
    assert response.status_code == 201
    client_info = response.json()

    response = await client.post(
        "/token",
        data={
            "grant_type": TOKEN_EXCHANGE_GRANT_TYPE,
            "client_id": client_info["client_id"],
            "subject_token": VALID_SUBJECT_TOKEN,
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
        },
        auth=(client_info["client_id"], client_info["client_secret"]),
    )

    assert response.status_code == 200, response.content
    assert response.json()["access_token"] in provider.tokens


@pytest.mark.anyio
async def test_token_exchange_actor_token_without_type_is_rejected(client: httpx.AsyncClient):
    client_info = await register(client)

    response = await client.post(
        "/token",
        data={
            "grant_type": TOKEN_EXCHANGE_GRANT_TYPE,
            "client_id": client_info["client_id"],
            "client_secret": client_info["client_secret"],
            "subject_token": VALID_SUBJECT_TOKEN,
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "actor_token": "some-actor-token",
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "invalid_request"
    assert "actor_token_type" in body["error_description"]


@pytest.mark.anyio
async def test_token_exchange_actor_token_type_without_token_is_rejected(client: httpx.AsyncClient):
    client_info = await register(client)

    response = await client.post(
        "/token",
        data={
            "grant_type": TOKEN_EXCHANGE_GRANT_TYPE,
            "client_id": client_info["client_id"],
            "client_secret": client_info["client_secret"],
            "subject_token": VALID_SUBJECT_TOKEN,
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "actor_token_type": "urn:ietf:params:oauth:token-type:jwt",
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "invalid_request"
    assert "actor_token_type" in body["error_description"]


@pytest.mark.anyio
async def test_token_exchange_rejected_when_disabled(provider: TokenExchangeProvider):
    """With token_exchange_enabled=False the /token endpoint refuses the grant even if the provider supports it."""
    routes = create_auth_routes(
        provider,
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=["mcp"]),
        revocation_options=RevocationOptions(enabled=False),
        token_exchange_enabled=False,
    )
    app = Starlette(routes=routes)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://auth.example.com") as http:
        client_info = await register(http)
        response = await http.post(
            "/token",
            data={
                "grant_type": TOKEN_EXCHANGE_GRANT_TYPE,
                "client_id": client_info["client_id"],
                "client_secret": client_info["client_secret"],
                "subject_token": VALID_SUBJECT_TOKEN,
                "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"
    # The provider was never consulted.
    assert provider.last_params is None


@pytest.mark.anyio
async def test_token_exchange_rejected_when_grant_not_registered(client: httpx.AsyncClient):
    response = await client.post(
        "/register",
        json={
            "redirect_uris": ["https://client.example.com/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
        },
    )
    assert response.status_code == 201
    client_info = response.json()

    response = await client.post(
        "/token",
        data={
            "grant_type": TOKEN_EXCHANGE_GRANT_TYPE,
            "client_id": client_info["client_id"],
            "client_secret": client_info["client_secret"],
            "subject_token": VALID_SUBJECT_TOKEN,
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"


@pytest.mark.anyio
async def test_default_provider_rejects_token_exchange():
    """A provider that does not override `exchange_token` rejects with unsupported_grant_type."""

    class BareProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
        async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
            raise NotImplementedError

        async def register_client(self, client_info: OAuthClientInformationFull) -> None:
            raise NotImplementedError

        async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
            raise NotImplementedError

        async def load_authorization_code(
            self, client: OAuthClientInformationFull, authorization_code: str
        ) -> AuthorizationCode | None:
            raise NotImplementedError

        async def exchange_authorization_code(
            self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
        ) -> OAuthToken:
            raise NotImplementedError

        async def load_refresh_token(
            self, client: OAuthClientInformationFull, refresh_token: str
        ) -> RefreshToken | None:
            raise NotImplementedError

        async def exchange_refresh_token(
            self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
        ) -> OAuthToken:
            raise NotImplementedError

        async def load_access_token(self, token: str) -> AccessToken | None:
            raise NotImplementedError

        async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
            raise NotImplementedError

    bare = BareProvider()
    client_info = OAuthClientInformationFull(
        redirect_uris=None,
        client_id="c",
        grant_types=[TOKEN_EXCHANGE_GRANT_TYPE],
    )
    params = TokenExchangeParams(
        subject_token=VALID_SUBJECT_TOKEN,
        subject_token_type="urn:ietf:params:oauth:token-type:jwt",
    )
    with pytest.raises(TokenError) as excinfo:
        await bare.exchange_token(client_info, params)
    assert excinfo.value.error == "unsupported_grant_type"
