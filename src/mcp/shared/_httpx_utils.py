"""Utilities for creating standardized httpx2 AsyncClient instances."""

import ipaddress
import logging
from enum import Enum
from typing import Any, Protocol

import httpx2

logger = logging.getLogger(__name__)

__all__ = [
    "create_mcp_http_client",
    "MCP_DEFAULT_TIMEOUT",
    "MCP_DEFAULT_SSE_READ_TIMEOUT",
    "RedirectPolicy",
]

# Default MCP timeout configuration
MCP_DEFAULT_TIMEOUT = 30.0  # General operations (seconds)
MCP_DEFAULT_SSE_READ_TIMEOUT = 300.0  # SSE streams - 5 minutes (seconds)

# Well-known names that resolve to loopback (RFC 6761 reserves *.localhost).
_LOOPBACK_HOSTNAMES = ("localhost", ".localhost")


class RedirectPolicy(Enum):
    """Controls how the MCP HTTP client handles server 3xx redirects.

    Streamable HTTP is JSON-RPC over HTTP; an attacker-influenced server can
    return a ``307``/``308`` that bounces the client's JSON-RPC traffic onto an
    internal or loopback endpoint (a local agent, a metadata service, a
    registry), and the client will accept that endpoint's reply as the MCP
    server's own. This is the client-side mirror of the server-side DNS
    rebinding protection in ``mcp.server.transport_security``.

    Attributes:
        NONE: Never follow redirects (``follow_redirects=False``).
        SAME_HOST: Only follow redirects that stay on the same scheme and host.
        SAFE: Follow any redirect whose target is not a loopback, link-local,
            private, multicast or otherwise non-global address. This is the
            default: legitimate public redirects (e.g. a migrated endpoint)
            still work, while bounce-into-internal attacks are blocked.
        ALL: Follow any redirect (the historical behavior). Primarily useful as
            an explicit opt-out.
    """

    NONE = "none"
    SAME_HOST = "same_host"
    SAFE = "safe"
    ALL = "all"


def _is_internal_or_non_global(host: str) -> bool:
    """Return True when a literal host is loopback/link-local/private/etc.

    Hostnames (other than the reserved ``localhost``/``*.localhost`` names) are
    treated as external, since a deterministic check would require resolving
    them via DNS from the event hook.
    """
    if not host:
        return True

    lower = host.lower().rstrip(".")
    if lower == "localhost" or lower.endswith(_LOOPBACK_HOSTNAMES):
        return True

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def _make_redirect_guard(policy: RedirectPolicy):
    """Build an httpx ``request`` event hook enforcing ``policy``.

    The hook is invoked for the initial request and for every redirect hop.
    The first request's origin authorizes whatever host the caller explicitly
    chose (a user may legitimately target their own loopback server); only
    subsequent hops are validated.
    """
    if policy is RedirectPolicy.NONE or policy is RedirectPolicy.ALL:
        return None

    origin: tuple | None = None

    async def guard(request) -> None:
        nonlocal origin
        target = (request.url.scheme, request.url.host, request.url.port)
        if origin is None:
            origin = target
            return
        if target == origin:
            return
        if policy is RedirectPolicy.SAME_HOST:
            if target[:2] != origin[:2]:
                raise httpx2.ConnectError(
                    f"Blocked redirect to a different host '{request.url}' (redirect policy: {policy.value})"
                )
        elif policy is RedirectPolicy.SAFE and _is_internal_or_non_global(target[1]):
            raise httpx2.ConnectError(
                f"Blocked redirect to internal/private host '{request.url}' "
                f"(redirect policy: {policy.value}); refusing to send JSON-RPC "
                f"traffic to a non-global address"
            )

    return guard


class McpHttpClientFactory(Protocol):  # pragma: no branch
    def __call__(  # pragma: no branch
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        redirect_policy: RedirectPolicy = RedirectPolicy.SAFE,
    ) -> httpx2.AsyncClient: ...


def create_mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx2.Timeout | None = None,
    auth: httpx2.Auth | None = None,
    redirect_policy: RedirectPolicy = RedirectPolicy.SAFE,
) -> httpx2.AsyncClient:
    """Create a standardized httpx2 AsyncClient with MCP defaults.

    Builds a client that follows redirects by default, applies an SSE-friendly
    default timeout, and protects against server-driven SSRF: redirect targets
    are validated so the client never bounces JSON-RPC traffic onto internal or
    loopback hosts (see ``RedirectPolicy``).

    Args:
        headers: Optional headers to include with all requests.
        timeout: Request timeout as httpx2.Timeout object. Defaults to 30s for
            connect/write/pool and 300s for read (for long-lived SSE streams).
        auth: Optional authentication handler.
        redirect_policy: How to handle server 3xx redirects. Defaults to
            ``RedirectPolicy.SAFE``, which blocks redirects into loopback,
            link-local, private and other non-global addresses while still
            following legitimate public redirects.

    Returns:
        Configured httpx2.AsyncClient instance with MCP defaults.

    Note:
        The returned AsyncClient must be used as a context manager to ensure
        proper cleanup of connections.

    Example:
        Basic usage with MCP defaults:

        ```python
        async with create_mcp_http_client() as client:
            response = await client.get("https://api.example.com")
        ```

        With custom headers:

        ```python
        headers = {"Authorization": "Bearer token"}
        async with create_mcp_http_client(headers) as client:
            response = await client.get("/endpoint")
        ```

        With both custom headers and timeout:

        ```python
        timeout = httpx2.Timeout(60.0, read=300.0)
        async with create_mcp_http_client(headers, timeout) as client:
            response = await client.get("/long-request")
        ```

        With authentication:

        ```python
        from httpx2 import BasicAuth
        auth = BasicAuth(username="user", password="pass")
        async with create_mcp_http_client(headers, timeout, auth) as client:
            response = await client.get("/protected-endpoint")
        ```
    """
    # Set MCP defaults
    kwargs: dict[str, Any] = {}

    if redirect_policy is RedirectPolicy.NONE:
        kwargs["follow_redirects"] = False
    else:
        kwargs["follow_redirects"] = True
        guard = _make_redirect_guard(redirect_policy)
        if guard is not None:
            kwargs["event_hooks"] = {"request": [guard]}

    # Handle timeout
    if timeout is None:
        kwargs["timeout"] = httpx2.Timeout(MCP_DEFAULT_TIMEOUT, read=MCP_DEFAULT_SSE_READ_TIMEOUT)
    else:
        kwargs["timeout"] = timeout

    # Handle headers
    if headers is not None:
        kwargs["headers"] = headers

    # Handle authentication
    if auth is not None:  # pragma: no cover
        kwargs["auth"] = auth

    return httpx2.AsyncClient(**kwargs)
