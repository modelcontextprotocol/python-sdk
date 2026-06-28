"""Minimal in-process OAuth pieces for the auth stories.

A story-shaped subset; ``tests/interaction/auth`` keeps its own (richer) provider.
"""

from __future__ import annotations

import os
import secrets
import time
from urllib.parse import parse_qs, urlsplit

import httpx

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientInformationFull, OAuthToken

BASE_URL = "http://127.0.0.1:8000"
MCP_URL = f"{BASE_URL}/mcp"
REDIRECT_URI = f"{BASE_URL}/oauth/callback"


class InMemoryTokenStorage:
    """A ``TokenStorage`` that keeps tokens and DCR client info on instance attributes."""

    tokens: OAuthToken | None = None
    client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


class HeadlessOAuth:
    """Completes the authorize redirect in-process via the bound ``httpx`` client."""

    def __init__(self) -> None:
        self.authorize_url: str | None = None
        self._http: httpx.AsyncClient | None = None
        self._result = AuthorizationCodeResult(code="", state=None)

    def bind(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client

    async def redirect_handler(self, authorization_url: str) -> None:
        assert self._http is not None
        self.authorize_url = authorization_url
        # ``auth=None`` is load-bearing: re-entering the locked auth flow would deadlock.
        response = await self._http.get(authorization_url, follow_redirects=False, auth=None)
        assert response.status_code == 302, f"authorize returned {response.status_code}: {response.text}"
        params = parse_qs(urlsplit(response.headers["location"]).query)
        self._result = AuthorizationCodeResult(code=params.get("code", [""])[0], state=params.get("state", [None])[0])

    async def callback_handler(self) -> AuthorizationCodeResult:
        return self._result


class InMemoryAuthorizationServerProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """Minimal demo AS: DCR + authorize + auth-code exchange held in instance dicts.

    ``authorize`` auto-consents only when ``OAUTH_DEMO_AUTO_CONSENT=1``; otherwise it redirects
    with ``error=interaction_required`` so a manual run shows where a real browser would open.
    """

    def __init__(self) -> None:
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.codes: dict[str, AuthorizationCode] = {}
        self.access_tokens: dict[str, AccessToken] = {}

    def mint_access_token(
        self, *, client_id: str, scopes: list[str], resource: str | None = None, subject: str | None = None
    ) -> str:
        access = f"access_{secrets.token_hex(16)}"
        self.access_tokens[access] = AccessToken(
            token=access,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time()) + 3600,
            resource=resource,
            subject=subject,
        )
        return access

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        assert client_info.client_id is not None
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        target = str(params.redirect_uri)
        if os.environ.get("OAUTH_DEMO_AUTO_CONSENT") != "1":
            return construct_redirect_uri(target, error="interaction_required", state=params.state)
        assert client.client_id is not None
        code = AuthorizationCode(
            code=f"code_{secrets.token_hex(16)}",
            client_id=client.client_id,
            scopes=params.scopes or ["mcp"],
            expires_at=time.time() + 300,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        self.codes[code.code] = code
        return construct_redirect_uri(target, code=code.code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return self.codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        scopes = authorization_code.scopes
        access = self.mint_access_token(
            client_id=authorization_code.client_id, scopes=scopes, resource=authorization_code.resource
        )
        del self.codes[authorization_code.code]
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=3600, scope=" ".join(scopes))

    async def load_access_token(self, token: str) -> AccessToken | None:
        return self.access_tokens.get(token)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        raise NotImplementedError

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        raise NotImplementedError

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        raise NotImplementedError


def auth_settings(
    *, required_scopes: list[str] | None = None, identity_assertion_enabled: bool = False
) -> AuthSettings:
    """``AuthSettings`` for the co-hosted demo AS+RS on the loopback origin, DCR enabled.

    ``identity_assertion_enabled`` passes through to the SEP-990 jwt-bearer grant flag.
    """
    scopes = required_scopes or ["mcp"]
    return AuthSettings(
        issuer_url=BASE_URL,  # type: ignore[arg-type]
        resource_server_url=MCP_URL,  # type: ignore[arg-type]
        required_scopes=scopes,
        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=scopes, default_scopes=scopes),
        identity_assertion_enabled=identity_assertion_enabled,
    )
