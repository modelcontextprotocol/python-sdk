"""Utilities for creating standardized httpx AsyncClient instances."""

from typing import Any, Protocol

import httpx

__all__ = [
    "create_mcp_http_client",
    "RedirectError",
    "MCP_DEFAULT_TIMEOUT",
    "MCP_DEFAULT_SSE_READ_TIMEOUT",
]

# Default MCP timeout configuration
MCP_DEFAULT_TIMEOUT = 30.0  # General operations (seconds)
MCP_DEFAULT_SSE_READ_TIMEOUT = 300.0  # SSE streams - 5 minutes (seconds)

_DEFAULT_PORTS = {"http": 80, "https": 443}


class RedirectError(httpx.HTTPStatusError):
    """Raised when a server redirects a request somewhere the client will not go automatically.

    Clients created by `create_mcp_http_client` follow redirects that stay on the
    same origin (scheme, host, and port), including http-to-https upgrades of the
    same host on default ports. Any other redirect raises this error instead of
    being followed, because everything configured on the client (headers, auth,
    request bodies) is sent to whichever server it talks to.
    """


class McpHttpClientFactory(Protocol):  # pragma: no branch
    def __call__(  # pragma: no branch
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient: ...


def _port_or_default(url: httpx.URL) -> int | None:
    if url.port is not None:
        return url.port
    return _DEFAULT_PORTS.get(url.scheme)


def _same_origin(url: httpx.URL, other: httpx.URL) -> bool:
    return url.scheme == other.scheme and url.host == other.host and _port_or_default(url) == _port_or_default(other)


def _is_https_upgrade(old_url: httpx.URL, new_url: httpx.URL) -> bool:
    # The one scheme change treated as staying on the same origin: the same
    # host moving from http on its default port to https on its default port.
    if old_url.host != new_url.host:
        return False
    return (
        old_url.scheme == "http"
        and new_url.scheme == "https"
        and _port_or_default(old_url) == 80
        and _port_or_default(new_url) == 443
    )


def _resolve_redirect_target(request_url: httpx.URL, location: str) -> httpx.URL:
    """Resolve a Location header value the way httpx builds its redirect URL."""
    url = httpx.URL(location)

    # An "absolute" Location with a scheme but no host keeps the request's
    # host. Only the host is copied - not the port - matching httpx.
    if url.scheme and not url.host:
        url = url.copy_with(host=request_url.host)

    # Location may be relative (RFC 9110 section 10.2.2).
    if url.is_relative_url:
        url = request_url.join(url)

    return url


def _redirect_allowed(request_url: httpx.URL, target: httpx.URL) -> bool:
    return _same_origin(target, request_url) or _is_https_upgrade(request_url, target)


def redirect_error(
    response: httpx.Response, *, context: str | None = None, target: httpx.URL | None = None
) -> RedirectError:
    """Build the error for a redirect response that will not be followed.

    Used both by the client factory's response hook (which only sees redirects
    leaving the origin, and passes the target it already resolved) and by
    transports that receive a redirect response from a client configured not
    to follow redirects at all.
    """
    request = response.request
    location = response.headers.get("location", "")
    prefix = f"{context}: " if context else ""
    if target is None:
        try:
            target = _resolve_redirect_target(request.url, location)
        except httpx.InvalidURL:
            return RedirectError(
                f"{prefix}server responded with {response.status_code} and an unparsable Location header {location!r}.",
                request=request,
                response=response,
            )
    if _redirect_allowed(request.url, target):
        # Only reachable with a client that does not follow redirects at all
        # (the factory's clients follow these): point at the final URL.
        message = (
            f"{prefix}server redirected this request to {str(target)!r} and the configured "
            "HTTP client does not follow redirects. Connect to that URL directly instead."
        )
    else:
        message = (
            f"{prefix}server at {request.url} responded with {response.status_code} redirecting to "
            f"{str(target)!r}, which is on a different origin. Redirects are only followed within "
            "the same origin (scheme, host, and port) or for an http-to-https upgrade of the same "
            "host. If the new location is correct, connect to it directly - note that headers and "
            "request bodies configured for this client are sent to whichever server it talks to. "
            "To follow other redirects, supply your own pre-configured httpx.AsyncClient."
        )
    return RedirectError(message, request=request, response=response)


async def _raise_on_disallowed_redirect(response: httpx.Response) -> None:
    """Response hook: stop redirects that leave the origin before they are followed."""
    if not response.has_redirect_location:
        return
    request = response.request
    try:
        target = _resolve_redirect_target(request.url, response.headers["location"])
    except httpx.InvalidURL:
        # Let httpx surface its own error for an unparsable Location.
        return
    if _redirect_allowed(request.url, target):
        return
    raise redirect_error(response, target=target)


def create_mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """Create a standardized httpx AsyncClient with MCP defaults.

    Follows redirects that stay on the same origin (scheme, host, and port),
    including http-to-https upgrades of the same host on default ports; any
    other redirect raises `RedirectError` instead of being followed. Applies
    an SSE-friendly default timeout.

    Args:
        headers: Optional headers to include with all requests.
        timeout: Request timeout as httpx.Timeout object. Defaults to 30s for
            connect/write/pool and 300s for read (for long-lived SSE streams).
        auth: Optional authentication handler.

    Returns:
        Configured httpx.AsyncClient instance with MCP defaults.

    Note:
        The returned AsyncClient must be used as a context manager to ensure
        proper cleanup of connections.

    Raises:
        RedirectError: When a response redirects to a different origin. Connect
            to the final URL directly, or supply your own pre-configured
            httpx.AsyncClient where following such redirects is intended.

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
        timeout = httpx.Timeout(60.0, read=300.0)
        async with create_mcp_http_client(headers, timeout) as client:
            response = await client.get("/long-request")
        ```

        With authentication:

        ```python
        from httpx import BasicAuth
        auth = BasicAuth(username="user", password="pass")
        async with create_mcp_http_client(headers, timeout, auth) as client:
            response = await client.get("/protected-endpoint")
        ```
    """
    # Set MCP defaults
    kwargs: dict[str, Any] = {
        "follow_redirects": True,
        "event_hooks": {"response": [_raise_on_disallowed_redirect]},
    }

    # Handle timeout
    if timeout is None:
        kwargs["timeout"] = httpx.Timeout(MCP_DEFAULT_TIMEOUT, read=MCP_DEFAULT_SSE_READ_TIMEOUT)
    else:
        kwargs["timeout"] = timeout

    # Handle headers
    if headers is not None:
        kwargs["headers"] = headers

    # Handle authentication
    if auth is not None:  # pragma: no cover
        kwargs["auth"] = auth

    return httpx.AsyncClient(**kwargs)
