"""An in-memory implementation of the SDK's OAuth authorization-server provider protocol.

The provider holds clients, authorization codes, refresh tokens and access tokens in plain
instance dicts so tests can inspect them; tokens are minted from `secrets.token_hex` so the
values are unique without being predictable. The behaviour mirrors what the SDK's authorization
handlers expect: `authorize` immediately mints a code and returns the redirect, `exchange_*`
issue and rotate tokens, and `load_*` are simple lookups. Only the parts the auth interaction
suite drives are implemented; methods the suite does not exercise raise `NotImplementedError`.
"""

import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    TokenExchangeParams,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken, TokenExchangeToken
from tests.interaction._connect import BASE_URL

_TOKEN_LIFETIME_SECONDS = 3600

# The only subject token the in-memory provider accepts as a valid ID-JAG; any other value is
# rejected with invalid_grant, standing in for signature/policy validation a real AS performs.
VALID_SUBJECT_TOKEN = "valid-id-jag"


class InMemoryAuthorizationServerProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """An OAuth authorization-server provider backed by in-memory dicts.

    Holds registered clients, issued codes, refresh tokens and access tokens as instance state
    so tests can both drive the SDK's authorization handlers and inspect what was issued.

    Knobs:
        `default_scopes`: scopes granted when an authorize request supplies none.
        `deny_authorize`: every authorize request returns an `error=access_denied` redirect.
        `issue_expired_first`: the first issued token's `expires_in` is in the past so the
            client immediately considers it expired and refreshes; the server-side
            `AccessToken.expires_at` stays in the future so the bearer middleware accepts it
            on the retry that completes the connect.
        `fail_next_refresh`: the next refresh-token exchange raises `invalid_grant` once.
        `reject_all_tokens`: `load_access_token` returns None for every token, so the bearer
            middleware 401s every authenticated request.
    """

    def __init__(
        self,
        *,
        default_scopes: list[str] | None = None,
        deny_authorize: bool = False,
        issue_expired_first: bool = False,
        fail_next_refresh: bool = False,
        reject_all_tokens: bool = False,
        issuer: str | None = None,
    ) -> None:
        self._default_scopes = list(default_scopes) if default_scopes is not None else ["mcp"]
        # The authorization-response iss must equal the AS metadata issuer the client recorded
        # (RFC 9207 simple string comparison). `real_asm` builds the issuer from an AnyHttpUrl
        # object, so it carries the trailing slash; the redirect iss matches it. Path-issuer
        # tests pass the recorded issuer explicitly.
        self._issuer = issuer if issuer is not None else f"{BASE_URL}/"
        self._deny_authorize = deny_authorize
        self._issue_expired_first = issue_expired_first
        self._fail_next_refresh = fail_next_refresh
        self._reject_all_tokens = reject_all_tokens
        self._tokens_issued = 0
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.codes: dict[str, AuthorizationCode] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}
        self.access_tokens: dict[str, AccessToken] = {}
        # The most recent token-exchange request the SDK handler passed to exchange_token, for
        # tests to assert what the client sent (None until the first exchange).
        self.last_exchange_params: TokenExchangeParams | None = None

    def _next_expires_in(self) -> int:
        self._tokens_issued += 1
        if self._issue_expired_first and self._tokens_issued == 1:
            return -_TOKEN_LIFETIME_SECONDS
        return _TOKEN_LIFETIME_SECONDS

    def mint_access_token(self, *, client_id: str, scopes: list[str], resource: str | None = None) -> str:
        """Mint and store an access token, returning its value.

        Used by the auth-code and refresh exchanges and by the M2M `/token` shim. The
        server-side `expires_at` is always in the future regardless of `issue_expired_first`,
        which only affects what the client is told.
        """
        access = f"access_{secrets.token_hex(16)}"
        self.access_tokens[access] = AccessToken(
            token=access,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time()) + _TOKEN_LIFETIME_SECONDS,
            resource=resource,
        )
        return access

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        assert client_info.client_id is not None
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Mint an authorization code immediately and return the redirect carrying it.

        A real provider would interpose user consent here; the test provider grants
        unconditionally so the headless redirect handler can complete the flow in-process.
        When `deny_authorize` is set, returns an `error=access_denied` redirect instead.
        """
        assert client.client_id is not None
        if self._deny_authorize:
            return construct_redirect_uri(
                str(params.redirect_uri), error="access_denied", error_description="user denied", state=params.state
            )
        code = AuthorizationCode(
            code=f"code_{secrets.token_hex(16)}",
            client_id=client.client_id,
            scopes=params.scopes or self._default_scopes,
            expires_at=time.time() + 300,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        self.codes[code.code] = code
        # `iss` is RFC 9207's authorization-response issuer identifier — an extra parameter many
        # real authorization servers send. Including it on every success redirect proves the
        # client tolerates unrecognized callback parameters (RFC 6749 §4.1.2 MUST) by virtue of
        # every flow test passing unchanged.
        return construct_redirect_uri(str(params.redirect_uri), code=code.code, state=params.state, iss=self._issuer)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return self.codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Mint an access token and a refresh token for a valid authorization code, then consume the code."""
        assert client.client_id is not None
        access = self.mint_access_token(
            client_id=client.client_id, scopes=authorization_code.scopes, resource=authorization_code.resource
        )
        refresh = f"refresh_{secrets.token_hex(16)}"
        self.refresh_tokens[refresh] = RefreshToken(
            token=refresh,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
        )
        del self.codes[authorization_code.code]
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=self._next_expires_in(),
            scope=" ".join(authorization_code.scopes),
            refresh_token=refresh,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        if self._reject_all_tokens:
            return None
        return self.access_tokens.get(token)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        return self.refresh_tokens.get(refresh_token)

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        """Mint a new access token and rotate the refresh token, consuming the old one."""
        assert client.client_id is not None
        if self._fail_next_refresh:
            self._fail_next_refresh = False
            raise TokenError(error="invalid_grant", error_description="refresh denied by harness")
        access = self.mint_access_token(client_id=client.client_id, scopes=scopes)
        new_refresh = f"refresh_{secrets.token_hex(16)}"
        self.refresh_tokens[new_refresh] = RefreshToken(token=new_refresh, client_id=client.client_id, scopes=scopes)
        del self.refresh_tokens[refresh_token.token]
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=self._next_expires_in(),
            scope=" ".join(scopes),
            refresh_token=new_refresh,
        )

    async def exchange_token(self, client: OAuthClientInformationFull, params: TokenExchangeParams) -> OAuthToken:
        """Validate the ID-JAG subject token and mint an MCP access token (RFC 8693 / SEP-990).

        Records `params` for inspection and rejects any subject token other than
        `VALID_SUBJECT_TOKEN` with invalid_grant (standing in for signature/policy validation). The
        granted scopes are exactly those the client requested; a real provider would derive them
        from the validated ID-JAG and policy.
        """
        self.last_exchange_params = params
        assert client.client_id is not None
        if params.subject_token != VALID_SUBJECT_TOKEN:
            raise TokenError(error="invalid_grant", error_description="subject token is not valid")
        scopes = params.scopes if params.scopes is not None else self._default_scopes
        access = self.mint_access_token(client_id=client.client_id, scopes=scopes, resource=params.resource)
        return TokenExchangeToken(
            access_token=access,
            token_type="Bearer",
            expires_in=self._next_expires_in(),
            scope=" ".join(scopes),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Not exercised by this suite; revocation is out of scope for the interaction tests."""
        raise NotImplementedError
