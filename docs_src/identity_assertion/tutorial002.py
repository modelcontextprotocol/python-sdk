import secrets
import time

import jwt
from pydantic import AnyHttpUrl
from starlette.applications import Starlette

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    IdentityAssertionParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
)
from mcp.server.auth.routes import create_auth_routes
from mcp.shared.auth import JWT_BEARER_GRANT_TYPE, OAuthClientInformationFull, OAuthToken

ISSUER = "https://auth.example.com"
MCP_SERVER = "http://localhost:8001/mcp"
IDP_ISSUER = "https://idp.example.com"
IDP_SIGNING_KEY = "the-enterprise-idp-signing-key"

REGISTERED_CLIENTS = {
    "finance-agent": OAuthClientInformationFull(
        client_id="finance-agent",
        client_secret="finance-agent-secret",
        redirect_uris=None,
        grant_types=[JWT_BEARER_GRANT_TYPE],
        token_endpoint_auth_method="client_secret_post",
    )
}


class EnterpriseAuthorizationServer(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self) -> None:
        self.access_tokens: dict[str, AccessToken] = {}
        self.seen_jtis: set[str] = set()

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return REGISTERED_CLIENTS.get(client_id)

    async def load_access_token(self, token: str) -> AccessToken | None:
        return self.access_tokens.get(token)

    async def exchange_identity_assertion(
        self, client: OAuthClientInformationFull, params: IdentityAssertionParams
    ) -> OAuthToken:
        try:
            header = jwt.get_unverified_header(params.assertion)
            claims = jwt.decode(
                params.assertion,
                IDP_SIGNING_KEY,
                algorithms=["HS256"],
                issuer=IDP_ISSUER,
                audience=ISSUER,
                options={"require": ["iss", "sub", "aud", "exp", "iat", "jti", "client_id", "resource", "scope"]},
            )
        except jwt.InvalidTokenError as error:
            raise TokenError("invalid_grant", "the assertion did not verify") from error
        if header.get("typ") != "oauth-id-jag+jwt":
            raise TokenError("invalid_grant", "the assertion is not an ID-JAG")
        if claims["client_id"] != client.client_id:
            raise TokenError("invalid_grant", "the assertion was issued to a different client")
        if claims["resource"] != MCP_SERVER:
            raise TokenError("invalid_target", "the assertion is for a resource this server does not serve")
        if claims["jti"] in self.seen_jtis:
            raise TokenError("invalid_grant", "the assertion has already been used")
        self.seen_jtis.add(claims["jti"])
        scopes = claims["scope"].split()
        access_token = f"mcp_{secrets.token_hex(16)}"
        self.access_tokens[access_token] = AccessToken(
            token=access_token,
            client_id=claims["client_id"],
            scopes=scopes,
            expires_at=int(time.time()) + 300,
            resource=claims["resource"],
            subject=claims["sub"],
        )
        return OAuthToken(access_token=access_token, token_type="Bearer", expires_in=300, scope=" ".join(scopes))

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        raise AuthorizeError("unauthorized_client", "this authorization server only accepts ID-JAGs")

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> None:
        return None

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        raise TokenError("invalid_grant", "this authorization server only accepts ID-JAGs")

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> None:
        return None

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        raise TokenError("invalid_grant", "this authorization server only accepts ID-JAGs")


provider = EnterpriseAuthorizationServer()
auth_app = Starlette(
    routes=create_auth_routes(provider, issuer_url=AnyHttpUrl(ISSUER), identity_assertion_enabled=True)
)
