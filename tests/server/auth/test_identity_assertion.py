"""Server-side SEP-990 Identity Assertion Authorization Grant (RFC 7523 jwt-bearer) handling."""

import secrets
import time

import httpx2
import pytest
from httpx2 import ASGITransport
from pydantic import AnyHttpUrl
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
from mcp.server.auth.routes import build_metadata, create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import JWT_BEARER_GRANT_TYPE, OAuthClientInformationFull, OAuthToken

ID_JAG_GRANT_PROFILE = "urn:ietf:params:oauth:grant-profile:id-jag"
VALID_ASSERTION = "valid-id-jag"
CONFIDENTIAL_CLIENT_ID = "enterprise-client"
CONFIDENTIAL_CLIENT_SECRET = "enterprise-secret"


class IdentityAssertionProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """A provider that implements `exchange_identity_assertion`; everything else is unused here."""

    def __init__(self) -> None:
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.tokens: dict[str, AccessToken] = {}
        self.last_params: IdentityAssertionParams | None = None

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

    async def exchange_identity_assertion(
        self, client: OAuthClientInformationFull, params: IdentityAssertionParams
    ) -> OAuthToken:
        self.last_params = params
        # Stand-in for RFC 7523 §3 / SEP-990 §5.1 assertion validation.
        if params.assertion != VALID_ASSERTION:
            raise TokenError(error="invalid_grant", error_description="assertion is not valid")
        assert client.client_id is not None
        scopes = params.scopes or ["mcp"]
        access = f"access_{secrets.token_hex(16)}"
        self.tokens[access] = AccessToken(
            token=access,
            client_id=client.client_id,
            scopes=scopes,
            expires_at=int(time.time()) + 3600,
            resource=params.resource,
            subject="assertion-user",
        )
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=3600, scope=" ".join(scopes))


@pytest.fixture
def provider() -> IdentityAssertionProvider:
    prov = IdentityAssertionProvider()
    # Pre-register a confidential client (DCR refuses the grant; see the DCR test).
    prov.clients[CONFIDENTIAL_CLIENT_ID] = OAuthClientInformationFull(
        client_id=CONFIDENTIAL_CLIENT_ID,
        client_secret=CONFIDENTIAL_CLIENT_SECRET,
        redirect_uris=None,
        grant_types=[JWT_BEARER_GRANT_TYPE],
        token_endpoint_auth_method="client_secret_post",
        scope="mcp",
    )
    return prov


@pytest.fixture
def app(provider: IdentityAssertionProvider) -> Starlette:
    routes = create_auth_routes(
        provider,
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=["mcp"]),
        revocation_options=RevocationOptions(enabled=False),
        identity_assertion_enabled=True,
    )
    return Starlette(routes=routes)


@pytest.fixture
async def client(app: Starlette):
    transport = ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://auth.example.com") as http:
        yield http


def assertion_form(**overrides: str) -> dict[str, str]:
    form = {
        "grant_type": JWT_BEARER_GRANT_TYPE,
        "client_id": CONFIDENTIAL_CLIENT_ID,
        "client_secret": CONFIDENTIAL_CLIENT_SECRET,
        "assertion": VALID_ASSERTION,
    }
    form.update(overrides)
    return form


def test_build_metadata_advertises_id_jag_profile_when_enabled():
    enabled = build_metadata(
        AnyHttpUrl("https://auth.example.com"),
        None,
        ClientRegistrationOptions(),
        RevocationOptions(),
        supports_identity_assertion=True,
    )
    assert JWT_BEARER_GRANT_TYPE in (enabled.grant_types_supported or [])
    assert enabled.authorization_grant_profiles_supported == [ID_JAG_GRANT_PROFILE]
    # The grant is confidential-only, so the `none` auth method is NOT advertised.
    assert "none" not in (enabled.token_endpoint_auth_methods_supported or [])

    disabled = build_metadata(
        AnyHttpUrl("https://auth.example.com"),
        None,
        ClientRegistrationOptions(),
        RevocationOptions(),
    )
    assert JWT_BEARER_GRANT_TYPE not in (disabled.grant_types_supported or [])
    assert disabled.authorization_grant_profiles_supported is None


@pytest.mark.anyio
async def test_metadata_endpoint_lists_id_jag_profile(client: httpx2.AsyncClient):
    response = await client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    body = response.json()
    assert JWT_BEARER_GRANT_TYPE in body["grant_types_supported"]
    assert body["authorization_grant_profiles_supported"] == [ID_JAG_GRANT_PROFILE]


@pytest.mark.anyio
async def test_identity_assertion_success(client: httpx2.AsyncClient, provider: IdentityAssertionProvider):
    response = await client.post("/token", data=assertion_form(scope="mcp", resource="https://mcp.example.com/mcp"))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert "issued_token_type" not in body  # plain RFC 6749 response under jwt-bearer

    issued = await provider.load_access_token(body["access_token"])
    assert issued is not None
    assert issued.scopes == ["mcp"]
    assert issued.subject == "assertion-user"

    assert provider.last_params is not None
    assert provider.last_params.assertion == VALID_ASSERTION
    assert provider.last_params.scopes == ["mcp"]
    assert provider.last_params.resource == "https://mcp.example.com/mcp"


@pytest.mark.anyio
async def test_identity_assertion_invalid_assertion(client: httpx2.AsyncClient):
    response = await client.post("/token", data=assertion_form(assertion="forged"))

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_grant", "error_description": "assertion is not valid"}


@pytest.mark.anyio
async def test_identity_assertion_rejected_when_disabled(provider: IdentityAssertionProvider):
    routes = create_auth_routes(
        provider,
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=["mcp"]),
        revocation_options=RevocationOptions(enabled=False),
        identity_assertion_enabled=False,
    )
    app = Starlette(routes=routes)
    transport = ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://auth.example.com") as http:
        response = await http.post("/token", data=assertion_form())

    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"
    assert provider.last_params is None


@pytest.mark.anyio
async def test_identity_assertion_rejects_public_client(
    client: httpx2.AsyncClient, provider: IdentityAssertionProvider
):
    """A public (auth method 'none') client cannot use the grant, even if it presents a valid assertion."""
    provider.clients["public-client"] = OAuthClientInformationFull(
        client_id="public-client",
        redirect_uris=None,
        grant_types=[JWT_BEARER_GRANT_TYPE],
        token_endpoint_auth_method="none",
        scope="mcp",
    )

    response = await client.post(
        "/token",
        data={"grant_type": JWT_BEARER_GRANT_TYPE, "client_id": "public-client", "assertion": VALID_ASSERTION},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "unauthorized_client"
    assert provider.last_params is None


@pytest.mark.anyio
async def test_identity_assertion_rejects_secretless_confidential_client(
    client: httpx2.AsyncClient, provider: IdentityAssertionProvider
):
    """A client registered with a secret-based method but no stored secret fails authentication.

    `ClientAuthenticator` rejects this misconfiguration as `invalid_client`, so the request never
    reaches the jwt-bearer handler or the provider hook.
    """
    provider.clients["secretless-client"] = OAuthClientInformationFull(
        client_id="secretless-client",
        client_secret=None,
        redirect_uris=None,
        grant_types=[JWT_BEARER_GRANT_TYPE],
        token_endpoint_auth_method="client_secret_post",
        scope="mcp",
    )

    response = await client.post(
        "/token",
        data={"grant_type": JWT_BEARER_GRANT_TYPE, "client_id": "secretless-client", "assertion": VALID_ASSERTION},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "invalid_client"
    assert "no stored secret" in body["error_description"]
    assert provider.last_params is None


@pytest.mark.anyio
async def test_malformed_request_missing_assertion_is_invalid_request(client: httpx2.AsyncClient):
    """A jwt-bearer request without the required `assertion` fails validation with invalid_request."""
    response = await client.post(
        "/token",
        data={
            "grant_type": JWT_BEARER_GRANT_TYPE,
            "client_id": CONFIDENTIAL_CLIENT_ID,
            "client_secret": CONFIDENTIAL_CLIENT_SECRET,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@pytest.mark.anyio
async def test_client_without_the_grant_registered_is_rejected(
    client: httpx2.AsyncClient, provider: IdentityAssertionProvider
):
    """A confidential client whose registration omits the jwt-bearer grant is refused the grant."""
    provider.clients["no-grant-client"] = OAuthClientInformationFull(
        client_id="no-grant-client",
        client_secret="s",
        redirect_uris=None,
        grant_types=["authorization_code"],
        token_endpoint_auth_method="client_secret_post",
        scope="mcp",
    )

    response = await client.post(
        "/token",
        data={
            "grant_type": JWT_BEARER_GRANT_TYPE,
            "client_id": "no-grant-client",
            "client_secret": "s",
            "assertion": VALID_ASSERTION,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"
    assert provider.last_params is None


@pytest.mark.anyio
async def test_dcr_refuses_to_register_the_jwt_bearer_grant(
    client: httpx2.AsyncClient, provider: IdentityAssertionProvider
):
    """Dynamic client registration rejects the jwt-bearer grant; the ID-JAG flow needs pre-registration."""
    response = await client.post(
        "/register",
        json={
            "redirect_uris": ["https://client.example.com/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "grant_types": ["authorization_code", JWT_BEARER_GRANT_TYPE],
            "response_types": ["code"],
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "invalid_client_metadata"
    assert JWT_BEARER_GRANT_TYPE in body["error_description"]

    # A registration without the jwt-bearer grant still succeeds and is stored.
    ok = await client.post(
        "/register",
        json={
            "redirect_uris": ["https://client.example.com/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
        },
    )
    assert ok.status_code == 201
    assert ok.json()["client_id"] in provider.clients


@pytest.mark.anyio
async def test_default_provider_rejects_identity_assertion():
    """A provider that does not override `exchange_identity_assertion` rejects with unsupported_grant_type."""

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
        grant_types=[JWT_BEARER_GRANT_TYPE],
    )
    params = IdentityAssertionParams(assertion=VALID_ASSERTION)
    with pytest.raises(TokenError) as excinfo:
        await bare.exchange_identity_assertion(client_info, params)
    assert excinfo.value.error == "unsupported_grant_type"
