"""Authorization-server side of SEP-990 (enterprise IdP policy controls).

An authorization server enables the RFC 8693 token-exchange grant by setting
`token_exchange_enabled=True` and implementing `exchange_token` on its provider. The
provider validates the subject token (the ID-JAG issued by the enterprise IdP), decides which
scopes the exchange may grant, and mints an MCP access token.

Two responsibilities are the provider's and must not be skipped (both are stubbed here):
- Validate the ID-JAG: signature against the IdP's keys, issuer/audience/expiry, and the
  organization's policy. Returning a subject for any non-empty token, as `_validate_id_jag`
  does below, is NOT safe for production.
- Narrow the granted scopes. The scopes a client requests must never be granted verbatim; the
  ID-JAG and policy determine what is permitted. `_grant_scopes` intersects the request with
  what the subject is allowed.

Wire the returned routes into a Starlette app with `create_auth_routes(...,
token_exchange_enabled=True)`, or set `AuthSettings(token_exchange_enabled=True)` when using
`MCPServer`/`Server` with an `auth_server_provider`.
"""

import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    TokenExchangeParams,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken, TokenExchangeToken

# The scopes this server is willing to grant via token exchange. A real implementation derives
# the permitted set from the validated ID-JAG and the organization's policy, not from a constant.
ALLOWED_SCOPES = ("mcp",)


class TokenExchangeProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """Authorization-server provider that accepts an ID-JAG via RFC 8693 token exchange."""

    def __init__(self) -> None:
        self.access_tokens: dict[str, AccessToken] = {}

    async def exchange_token(self, client: OAuthClientInformationFull, params: TokenExchangeParams) -> OAuthToken:
        subject = self._validate_id_jag(params.subject_token)
        if subject is None:
            raise TokenError(error="invalid_grant", error_description="Invalid or rejected subject token")

        scopes = self._grant_scopes(params.scopes)

        assert client.client_id is not None
        access_token = f"access_{secrets.token_hex(16)}"
        self.access_tokens[access_token] = AccessToken(
            token=access_token,
            client_id=client.client_id,
            scopes=scopes,
            expires_at=int(time.time()) + 3600,
            resource=params.resource,
            subject=subject,
        )
        # TokenExchangeToken sets RFC 8693's issued_token_type; it defaults to the access-token type.
        return TokenExchangeToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(scopes),
        )

    def _validate_id_jag(self, subject_token: str) -> str | None:
        """Validate the ID-JAG and return the subject, or None to reject.

        A real implementation verifies the JWT signature against the IdP's keys, checks the
        issuer/audience/expiry, and applies the organization's policy. This stub accepts any
        non-empty token and uses it as the subject identifier - replace it before production.
        """
        return subject_token or None

    def _grant_scopes(self, requested: list[str] | None) -> list[str]:
        """Return the scopes to grant, never exceeding what this server permits.

        Requested scopes are intersected with the allowed set so a valid ID-JAG can never be
        exchanged for broader access than policy allows; when none are requested, the full
        allowed set is granted.
        """
        if requested is None:
            return list(ALLOWED_SCOPES)
        granted = [scope for scope in requested if scope in ALLOWED_SCOPES]
        if not granted:
            raise TokenError(error="invalid_scope", error_description="No requested scope is permitted")
        return granted

    async def load_access_token(self, token: str) -> AccessToken | None:
        return self.access_tokens.get(token)
