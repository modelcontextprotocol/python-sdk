"""SEP-990 authorization server + bearer-gated MCP server on one app; exports `build_app()`.

`identity_assertion_enabled=True` turns the RFC 7523 jwt-bearer grant on, and the provider's
`exchange_identity_assertion` validates the IdP-signed ID-JAG and mints an access token bound to
the user and resource the assertion names. The MCP server half is ordinary bearer auth.
"""

import jwt
from pydantic import BaseModel
from starlette.applications import Starlette

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import IdentityAssertionParams, TokenError
from mcp.server.mcpserver import MCPServer
from mcp.shared.auth import JWT_BEARER_GRANT_TYPE, OAuthClientInformationFull, OAuthToken
from stories._hosting import NO_DNS_REBIND, run_app_from_args
from stories._shared.auth import MCP_URL, InMemoryAuthorizationServerProvider, auth_settings

from .idp import IDP_ISSUER, IDP_SIGNING_KEY

# DEMO ONLY: never hard-code real credentials.
DEMO_CLIENT_ID = "finance-agent"
DEMO_CLIENT_SECRET = "demo-finance-agent-secret"
DEMO_SCOPE = "mcp"
# The exact `issuer` string this authorization server's metadata serves. The client must configure
# the byte-identical string: RFC 8414 issuer comparison is character for character.
ISSUER = str(auth_settings().issuer_url)


class Whoami(BaseModel):
    subject: str
    client_id: str
    scopes: list[str]


class IdentityAssertionAuthorizationServer(InMemoryAuthorizationServerProvider):
    """The demo in-process AS plus the SEP-990 hook: validate an ID-JAG, mint a bound token."""

    def __init__(self) -> None:
        super().__init__()
        self.seen_jtis: set[str] = set()
        # Pre-registered out of band. Dynamic client registration refuses the jwt-bearer grant,
        # so an ID-JAG client always arrives already known and already confidential.
        self.clients[DEMO_CLIENT_ID] = OAuthClientInformationFull(
            client_id=DEMO_CLIENT_ID,
            client_secret=DEMO_CLIENT_SECRET,
            redirect_uris=None,
            grant_types=[JWT_BEARER_GRANT_TYPE],
            token_endpoint_auth_method="client_secret_post",
        )

    async def exchange_identity_assertion(
        self, client: OAuthClientInformationFull, params: IdentityAssertionParams
    ) -> OAuthToken:
        """Validate the ID-JAG per RFC 7523 §3 and the SEP-990 processing rules, then issue the token."""
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
        if claims["resource"] != MCP_URL:
            raise TokenError("invalid_target", "the assertion is for a resource this server does not serve")
        if claims["jti"] in self.seen_jtis:
            raise TokenError("invalid_grant", "the assertion has already been used")
        self.seen_jtis.add(claims["jti"])
        # Everything on the issued token comes from the validated assertion, the audience
        # restriction above all: it binds the token to the ID-JAG's `resource` claim, never to
        # the client-controlled `params.resource`. No refresh token is returned either; the IdP
        # owns session lifetime by deciding whether to issue the next ID-JAG.
        scopes = claims["scope"].split()
        access = self.mint_access_token(
            client_id=claims["client_id"], scopes=scopes, resource=claims["resource"], subject=claims["sub"]
        )
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=3600, scope=" ".join(scopes))


def build_app() -> Starlette:
    provider = IdentityAssertionAuthorizationServer()
    # `auth_server_provider=` alone is enough: MCPServer derives a token verifier from it
    # (passing both trips the mutex guard).
    mcp = MCPServer(
        "identity-assertion-example",
        auth=auth_settings(required_scopes=[DEMO_SCOPE], identity_assertion_enabled=True),
        auth_server_provider=provider,
    )

    @mcp.tool(description="Return the end user the ID-JAG named, plus the authenticated client and scopes.")
    def whoami() -> Whoami:
        token = get_access_token()
        assert token is not None
        assert token.subject is not None
        return Whoami(subject=token.subject, client_id=token.client_id, scopes=token.scopes)

    return mcp.streamable_http_app(transport_security=NO_DNS_REBIND)


if __name__ == "__main__":
    run_app_from_args(build_app)
