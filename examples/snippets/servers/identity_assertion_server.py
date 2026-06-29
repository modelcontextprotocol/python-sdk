"""Authorization-server side of SEP-990 (Identity Assertion Authorization Grant).

Enable with `identity_assertion_enabled=True` (via `create_auth_routes` or `AuthSettings`) and
implement `exchange_identity_assertion` on the provider: the client presents the IdP-issued ID-JAG
using the RFC 7523 jwt-bearer grant, and the provider validates it and mints an MCP access token.
"""

import secrets
import time
from dataclasses import dataclass

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    IdentityAssertionParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


@dataclass
class IdJagClaims:
    """The trusted claims extracted from a validated ID-JAG."""

    subject: str
    client_id: str  # must match the authenticated client (SEP-990 §5.1)
    resource: str  # the MCP server the issued token must be audience-restricted to
    scopes: list[str]


class IdentityAssertionProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """Authorization-server provider that accepts an ID-JAG via the RFC 7523 jwt-bearer grant."""

    def __init__(self) -> None:
        self.access_tokens: dict[str, AccessToken] = {}
        # SEP-990 clients are pre-registered out of band (DCR refuses this grant) and must be
        # confidential; `get_client` must return them or the token endpoint 401s before the exchange.
        self.clients: dict[str, OAuthClientInformationFull] = {
            "enterprise-mcp-client": OAuthClientInformationFull(
                client_id="enterprise-mcp-client",
                client_secret="enterprise-mcp-secret",
                redirect_uris=None,
                grant_types=["urn:ietf:params:oauth:grant-type:jwt-bearer"],
                token_endpoint_auth_method="client_secret_post",
            )
        }

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def exchange_identity_assertion(
        self, client: OAuthClientInformationFull, params: IdentityAssertionParams
    ) -> OAuthToken:
        claims = self._decode_and_validate_id_jag(params.assertion, client)

        access_token = f"access_{secrets.token_hex(16)}"
        self.access_tokens[access_token] = AccessToken(
            token=access_token,
            client_id=claims.client_id,
            scopes=claims.scopes,
            expires_at=int(time.time()) + 3600,
            # Bind to the resource from the validated ID-JAG, not the client-controlled request.
            resource=claims.resource,
            subject=claims.subject,
        )
        # No refresh token: SEP-990 relies on the IdP re-issuing ID-JAGs to control session lifetime.
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(claims.scopes),
        )

    def _decode_and_validate_id_jag(self, assertion: str, client: OAuthClientInformationFull) -> IdJagClaims:
        """Verify the ID-JAG and return its trusted claims, or reject the request.

        Replace this stub per RFC 7523 §3 / SEP-990 §5.1: verify the signature, `iss`, `exp`, and
        `typ` (`oauth-id-jag+jwt`); require `aud` to identify this server and `client_id` to match
        the authenticated client; derive scopes from the ID-JAG and policy. Reject with
        `invalid_grant` (RFC 7523 §3.1 / RFC 6749 §5.2). The stub raises so copies fail closed.
        """
        raise NotImplementedError("Validate the ID-JAG (signature, iss/aud/exp/typ, client_id, resource)")

    async def load_access_token(self, token: str) -> AccessToken | None:
        return self.access_tokens.get(token)
