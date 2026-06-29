"""In-memory implementation of the SDK's OAuth authorization-server provider protocol.

State lives in plain instance dicts so tests can inspect it; only what the auth interaction
suite drives is implemented — unexercised methods raise `NotImplementedError`.
"""

import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    IdentityAssertionParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from tests.interaction._connect import BASE_URL

_TOKEN_LIFETIME_SECONDS = 3600

# The only ID-JAG assertion accepted; others get invalid_grant, standing in for real signature/policy validation.
VALID_ASSERTION = "valid-id-jag"


class InMemoryAuthorizationServerProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """OAuth authorization-server provider backed by in-memory dicts tests can inspect.

    Knobs:
        `default_scopes`: scopes granted when an authorize request supplies none.
        `deny_authorize`: every authorize request returns an `error=access_denied` redirect.
        `issue_expired_first`: the first token's `expires_in` is in the past so the client refreshes
            immediately; the server-side `expires_at` stays valid so the retry succeeds.
        `fail_next_refresh`: the next refresh-token exchange raises `invalid_grant`, once.
        `reject_all_tokens`: `load_access_token` returns None, so every authenticated request 401s.
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
        # Must string-match the AS metadata issuer the client recorded (RFC 9207); `real_asm` builds
        # it from AnyHttpUrl, hence the trailing slash. Path-issuer tests pass the issuer explicitly.
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
        # Last params passed to exchange_identity_assertion, for tests to assert what the client sent.
        self.last_assertion_params: IdentityAssertionParams | None = None

    def _next_expires_in(self) -> int:
        self._tokens_issued += 1
        if self._issue_expired_first and self._tokens_issued == 1:
            return -_TOKEN_LIFETIME_SECONDS
        return _TOKEN_LIFETIME_SECONDS

    def mint_access_token(self, *, client_id: str, scopes: list[str], resource: str | None = None) -> str:
        """Mint and store an access token; always valid server-side even with `issue_expired_first`."""
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
        """Mint a code and return the redirect immediately; a real provider would interpose user consent here."""
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
        # The RFC 9207 `iss` parameter on every success redirect also proves the client tolerates
        # unrecognized callback parameters (RFC 6749 §4.1.2 MUST).
        return construct_redirect_uri(str(params.redirect_uri), code=code.code, state=params.state, iss=self._issuer)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return self.codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
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

    async def exchange_identity_assertion(
        self, client: OAuthClientInformationFull, params: IdentityAssertionParams
    ) -> OAuthToken:
        """Validate the ID-JAG assertion and mint an access token (RFC 7523 jwt-bearer / SEP-990).

        Grants the requested scopes verbatim; a real provider would derive them from the validated ID-JAG.
        """
        self.last_assertion_params = params
        assert client.client_id is not None
        if params.assertion != VALID_ASSERTION:
            raise TokenError(error="invalid_grant", error_description="assertion is not valid")
        scopes = params.scopes if params.scopes is not None else self._default_scopes
        access = self.mint_access_token(client_id=client.client_id, scopes=scopes, resource=params.resource)
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=self._next_expires_in(),
            scope=" ".join(scopes),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        raise NotImplementedError
