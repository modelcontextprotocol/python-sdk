"""Minimal bearer-token authentication for MCP HTTP transports.

Provides `BearerAuth`, a lightweight `httpx.Auth` implementation with a two-method
contract (`token()` and `on_unauthorized()`). Use this when you have a token from
an external source — API keys, gateway-managed tokens, service accounts, enterprise
SSO pipelines — and don't need the full OAuth authorization-code flow.

For OAuth flows (authorization code with PKCE, dynamic client registration, token
refresh), use `OAuthClientProvider` instead. Both are `httpx.Auth` subclasses and
plug into the same `auth` parameter.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from dataclasses import dataclass

import httpx

from mcp.client.auth.exceptions import UnauthorizedError

TokenSource = str | Callable[[], str | None] | Callable[[], Awaitable[str | None]]
"""A bearer-token source: a static string, or a sync/async callable returning one."""

UnauthorizedHandler = Callable[["UnauthorizedContext"], Awaitable[None]]
"""Async handler invoked when the server responds with 401."""


@dataclass
class UnauthorizedContext:
    """Context passed to `on_unauthorized` when the server responds with 401.

    Handlers can inspect `response.headers["WWW-Authenticate"]` for resource metadata
    URLs and scope hints per RFC 6750 §3 and RFC 9728, then refresh credentials before
    the single retry.
    """

    response: httpx.Response
    """The 401 response. Body has been read — `response.text` / `response.json()` are safe."""

    request: httpx.Request
    """The request that was rejected. `request.url` is the MCP server URL."""


class BearerAuth(httpx.Auth):
    """Minimal bearer-token authentication for MCP HTTP transports.

    Implements `httpx.Auth` with a two-method contract:

    - `token()` — called before every request to obtain the current bearer token.
    - `on_unauthorized()` — called when the server responds with 401, giving the
      provider a chance to refresh credentials before the transport retries once.

    For static tokens (API keys, pre-provisioned credentials)::

        auth = BearerAuth("my-api-key")

    For dynamic tokens (read from environment, cache, or external service)::

        auth = BearerAuth(lambda: os.environ.get("MCP_TOKEN"))
        auth = BearerAuth(get_token_async)  # async callable

    For custom 401 handling (token refresh, re-authentication signal)::

        async def refresh(ctx: UnauthorizedContext) -> None:
            await my_token_cache.invalidate()

        auth = BearerAuth(get_token, on_unauthorized=refresh)

    Subclass and override `token()` / `on_unauthorized()` for more complex providers.

    For full OAuth 2.1 flows (authorization code with PKCE, discovery, registration),
    use `OAuthClientProvider` — both are `httpx.Auth` subclasses and accepted by the
    same `auth` parameter on transports.
    """

    def __init__(
        self,
        token: TokenSource | None = None,
        on_unauthorized: UnauthorizedHandler | None = None,
    ) -> None:
        """Initialize bearer-token authentication.

        Args:
            token: The bearer token source. A static string, a sync callable
                returning `str | None`, or an async callable returning `str | None`.
                Called before every request. If `None`, subclasses must override
                `token()`.
            on_unauthorized: Optional async handler called when the server responds
                with 401. After the handler returns, `token()` is called again and
                the request retried once. If not provided, 401 raises
                `UnauthorizedError` immediately. If the retry also gets 401,
                `UnauthorizedError` is raised.
        """
        self._token = token
        self._on_unauthorized = on_unauthorized

    async def token(self) -> str | None:
        """Return the current bearer token, or `None` if unavailable.

        Called before every request. The default implementation resolves the
        `token` argument passed to `__init__` (string, sync callable, or async
        callable). Override for custom retrieval logic.

        Implementations should be fast — return a cached value and refresh in the
        background rather than blocking on network calls here.
        """
        src = self._token
        if src is None or isinstance(src, str):
            return src
        result = src()
        if inspect.isawaitable(result):
            return await result
        return result

    async def on_unauthorized(self, context: UnauthorizedContext) -> None:
        """Handle a 401 response. Called once before the single retry.

        The default implementation delegates to the `on_unauthorized` callable
        passed to `__init__`, or raises `UnauthorizedError` if none was provided.
        Override to implement custom refresh logic.

        Implementations should refresh tokens, clear caches, or signal the host
        application — whatever is needed so the next `token()` call returns a
        valid token. Raise an exception to abort without retrying (e.g., when
        interactive user action is required before a retry could succeed).
        """
        if self._on_unauthorized is None:
            www_auth = context.response.headers.get("WWW-Authenticate", "")
            hint = f" (WWW-Authenticate: {www_auth})" if www_auth else ""
            raise UnauthorizedError(
                f"Server at {context.request.url} returned 401 Unauthorized{hint}; "
                "no on_unauthorized handler configured"
            )
        await self._on_unauthorized(context)

    def sync_auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        """Not supported — `BearerAuth` is async-only.

        Raises:
            RuntimeError: Always. Use `httpx.AsyncClient`, not `httpx.Client`.
        """
        raise RuntimeError(
            "BearerAuth is async-only because token() and on_unauthorized() are "
            "coroutines; use httpx.AsyncClient, not httpx.Client"
        )
        yield request  # pragma: no cover — unreachable; makes this a generator for type compat

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """httpx auth-flow integration.

        Each request gets a fresh generator instance, so retry state is naturally
        scoped per-operation — there is no shared retry counter to reset or leak
        across concurrent requests.
        """
        await self._apply_token(request)
        response = yield request

        if response.status_code == 401:
            await response.aread()
            await self.on_unauthorized(UnauthorizedContext(response=response, request=request))

            await self._apply_token(request)
            response = yield request

            if response.status_code == 401:
                raise UnauthorizedError(f"Server at {request.url} returned 401 Unauthorized after re-authentication")

    async def _apply_token(self, request: httpx.Request) -> None:
        token = await self.token()
        if token:
            request.headers["Authorization"] = f"Bearer {token}"
        else:
            request.headers.pop("Authorization", None)
