"""Authlib-backed OAuth2 adapter for MCP HTTPX integration.

Provides :class:`AuthlibOAuthAdapter`, an ``httpx.Auth`` plugin that wraps
``authlib.integrations.httpx_client.AsyncOAuth2Client`` to handle token
acquisition, automatic refresh, and Bearer-header injection.

The adapter is a drop-in replacement for :class:`~mcp.client.auth.OAuthClientProvider`
when you already have OAuth endpoints and credentials (i.e. no MCP-specific
metadata discovery is needed).  For full MCP discovery (PRM / OASM / DCR),
continue to use :class:`~mcp.client.auth.OAuthClientProvider`.

Supported grant types in this release:
- ``client_credentials`` — fully self-contained (no browser interaction)
- ``authorization_code`` + PKCE — requires *redirect_handler* / *callback_handler*

Example (client_credentials)::

    from mcp.client.auth import AuthlibAdapterConfig, AuthlibOAuthAdapter

    config = AuthlibAdapterConfig(
        token_endpoint="https://auth.example.com/token",
        client_id="my-client",
        client_secret="secret",
        scopes=["read", "write"],
    )
    adapter = AuthlibOAuthAdapter(config=config, storage=InMemoryTokenStorage())
    async with httpx.AsyncClient(auth=adapter) as client:
        resp = await client.get("https://api.example.com/resource")
"""

from __future__ import annotations

import logging
import secrets
import string
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, Protocol

import anyio
import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from mcp.client.auth.exceptions import OAuthFlowError
from mcp.client.auth.oauth2 import TokenStorage
from mcp.shared.auth import OAuthToken

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal protocol — typed interface for untyped Authlib client
# ---------------------------------------------------------------------------


class _AsyncOAuth2ClientProtocol(Protocol):
    """Minimal typed interface for authlib.integrations.httpx_client.AsyncOAuth2Client.

    Defined as a Protocol so that pyright strict mode can type-check all member
    accesses on the Authlib client without requiring upstream type stubs.
    """

    token: dict[str, Any] | None
    scope: str | None
    code_challenge_method: str

    async def fetch_token(self, url: str, **kwargs: Any) -> dict[str, Any]: ...

    def create_authorization_url(self, url: str, **kwargs: Any) -> tuple[str, str]: ...

    async def ensure_active_token(self, token: dict[str, Any]) -> None: ...


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class AuthlibAdapterConfig(BaseModel):
    """Configuration for :class:`AuthlibOAuthAdapter`.

    Args:
        token_endpoint: URL of the OAuth 2.0 token endpoint (required).
        client_id: OAuth client identifier (required).
        client_secret: OAuth client secret; omit for public clients.
        scopes: List of OAuth scopes to request.
        token_endpoint_auth_method: How to authenticate at the token endpoint.
            Accepted values: ``"client_secret_basic"`` (default),
            ``"client_secret_post"``, ``"none"``.
        authorization_endpoint: URL of the authorization endpoint.  When set,
            the adapter uses the *authorization_code + PKCE* grant on 401; when
            ``None`` (default) it uses *client_credentials*.
        redirect_uri: Redirect URI registered with the authorization server.
            Required when *authorization_endpoint* is set.
        leeway: Seconds before token expiry at which automatic refresh is
            triggered (default: 60).
        extra_token_params: Additional key-value pairs forwarded verbatim to
            every ``fetch_token`` call (e.g. ``{"audience": "..."}``).
    """

    token_endpoint: str
    client_id: str
    client_secret: str | None = Field(default=None, repr=False)  # excluded from repr to prevent secret leakage
    scopes: list[str] | None = None
    token_endpoint_auth_method: str = "client_secret_basic"
    # authorization_code flow (optional)
    authorization_endpoint: str | None = None
    redirect_uri: str | None = None
    # Authlib tuning
    leeway: int = 60
    extra_token_params: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class AuthlibOAuthAdapter(httpx.Auth):
    """Authlib-backed ``httpx.Auth`` provider.

    Wraps :class:`authlib.integrations.httpx_client.AsyncOAuth2Client` as a
    drop-in ``httpx.Auth`` plugin.  Token storage is delegated to the same
    :class:`~mcp.client.auth.TokenStorage` protocol used by the existing
    :class:`~mcp.client.auth.OAuthClientProvider`.

    Args:
        config: Adapter configuration (endpoints, credentials, scopes …).
        storage: Token persistence implementation.
        redirect_handler: Async callback that receives the authorization URL
            and opens it (browser, print, etc.).  Required for
            *authorization_code* flow.
        callback_handler: Async callback that waits for the user to complete
            authorization and returns ``(code, state)``.  Required for
            *authorization_code* flow.
    """

    requires_response_body = True

    def __init__(
        self,
        config: AuthlibAdapterConfig,
        storage: TokenStorage,
        redirect_handler: Callable[[str], Awaitable[None]] | None = None,
        callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None = None,
    ) -> None:
        self.config = config
        self.storage = storage
        self.redirect_handler = redirect_handler
        self.callback_handler = callback_handler
        self._lock: anyio.Lock = anyio.Lock()
        self._initialized: bool = False

        scope_str = " ".join(config.scopes) if config.scopes else None
        self._client: _AsyncOAuth2ClientProtocol = AsyncOAuth2Client(  # type: ignore[assignment]
            client_id=config.client_id,
            client_secret=config.client_secret,
            scope=scope_str,
            redirect_uri=config.redirect_uri,
            token_endpoint_auth_method=config.token_endpoint_auth_method,
            update_token=self._on_token_update,
            leeway=config.leeway,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _on_token_update(
        self,
        token: dict[str, Any],
        refresh_token: str | None = None,  # noqa: ARG002 (Authlib callback signature)
        access_token: str | None = None,  # noqa: ARG002
    ) -> None:
        """Authlib ``update_token`` callback — persists refreshed tokens."""
        oauth_token = OAuthToken(
            access_token=token["access_token"],
            token_type=token.get("token_type", "Bearer"),
            expires_in=token.get("expires_in"),
            scope=token.get("scope"),
            refresh_token=token.get("refresh_token"),
        )
        await self.storage.set_tokens(oauth_token)

    async def _initialize(self) -> None:
        """Load persisted tokens into the Authlib client on first use."""
        stored = await self.storage.get_tokens()
        if stored:
            token_dict: dict[str, Any] = {
                "access_token": stored.access_token,
                "token_type": stored.token_type,
            }
            if stored.refresh_token is not None:
                token_dict["refresh_token"] = stored.refresh_token
            if stored.scope is not None:
                token_dict["scope"] = stored.scope
            if stored.expires_in is not None:
                token_dict["expires_in"] = stored.expires_in
            self._client.token = token_dict
        self._initialized = True

    def _build_token_request_params(self) -> dict[str, Any]:
        """Merge base params with any extra params from config."""
        params: dict[str, Any] = {}
        if self.config.extra_token_params:
            params.update(self.config.extra_token_params)
        return params

    async def _fetch_client_credentials_token(self) -> None:
        """Acquire a token via the *client_credentials* grant."""
        params = self._build_token_request_params()
        await self._client.fetch_token(
            self.config.token_endpoint,
            grant_type="client_credentials",
            **params,
        )
        if self._client.token:
            await self._on_token_update(dict(self._client.token))

    async def _perform_authorization_code_flow(self) -> None:
        """Acquire a token via *authorization_code + PKCE* grant.

        Raises:
            OAuthFlowError: If *redirect_handler*, *callback_handler*,
                *authorization_endpoint*, or *redirect_uri* are missing.
        """
        if not self.config.authorization_endpoint:
            raise OAuthFlowError("authorization_endpoint is required for authorization_code flow")
        if not self.config.redirect_uri:
            raise OAuthFlowError("redirect_uri is required for authorization_code flow")
        if self.redirect_handler is None:
            raise OAuthFlowError("redirect_handler is required for authorization_code flow")
        if self.callback_handler is None:
            raise OAuthFlowError("callback_handler is required for authorization_code flow")

        # Generate PKCE state + build authorization URL via Authlib
        state = secrets.token_urlsafe(32)
        # Authlib generates code_verifier/code_challenge internally when
        # code_challenge_method is set on the client.
        self._client.code_challenge_method = "S256"
        # Generate a random code_verifier (Authlib will compute the challenge)
        code_verifier = "".join(secrets.choice(string.ascii_letters + string.digits + "-._~") for _ in range(128))

        auth_url, _ = self._client.create_authorization_url(
            self.config.authorization_endpoint,
            state=state,
            code_verifier=code_verifier,
        )

        await self.redirect_handler(auth_url)
        auth_code, returned_state = await self.callback_handler()

        if returned_state is None or not secrets.compare_digest(returned_state, state):
            raise OAuthFlowError(f"State mismatch: {returned_state!r} != {state!r}")
        if not auth_code:
            raise OAuthFlowError("No authorization code received from callback")

        params = self._build_token_request_params()
        await self._client.fetch_token(
            self.config.token_endpoint,
            grant_type="authorization_code",
            code=auth_code,
            redirect_uri=self.config.redirect_uri,
            code_verifier=code_verifier,
            **params,
        )
        if self._client.token:
            await self._on_token_update(dict(self._client.token))

    def _inject_bearer(self, request: httpx.Request) -> None:
        """Add ``Authorization: Bearer <token>`` header if a token is held."""
        token = self._client.token
        if token and token.get("access_token"):
            request.headers["Authorization"] = f"Bearer {token['access_token']}"

    # ------------------------------------------------------------------
    # httpx.Auth entry point
    # ------------------------------------------------------------------

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """HTTPX auth flow: ensure a valid token then inject it into the request.

        On a ``401`` response the adapter acquires a fresh token (via
        *client_credentials* or *authorization_code*) and retries once.
        """
        async with self._lock:
            if not self._initialized:
                await self._initialize()

            # Let Authlib auto-refresh if the token is close to expiry
            if self._client.token:
                await self._client.ensure_active_token(self._client.token)

            self._inject_bearer(request)

        response = yield request

        if response.status_code == 401:
            async with self._lock:
                # Acquire a brand-new token
                if self.config.authorization_endpoint:
                    await self._perform_authorization_code_flow()
                else:
                    await self._fetch_client_credentials_token()
                self._inject_bearer(request)

            yield request
