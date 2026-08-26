"""Utilities for creating and using httpx2 AsyncClient instances in the MCP transports."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

import httpx2

__all__ = ["create_mcp_http_client", "MCP_DEFAULT_TIMEOUT", "MCP_DEFAULT_SSE_READ_TIMEOUT"]

# Default MCP timeout configuration
MCP_DEFAULT_TIMEOUT = 30.0  # General operations (seconds)
MCP_DEFAULT_SSE_READ_TIMEOUT = 300.0  # SSE streams - 5 minutes (seconds)

# The headers httpx2.AsyncClient.sse() adds to an event-stream request.
_SSE_HEADERS = {"Accept": "text/event-stream", "Cache-Control": "no-store"}


class McpHttpClientFactory(Protocol):  # pragma: no branch
    def __call__(  # pragma: no branch
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
    ) -> httpx2.AsyncClient: ...


def create_mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx2.Timeout | None = None,
    auth: httpx2.Auth | None = None,
) -> httpx2.AsyncClient:
    """Create an httpx2 AsyncClient with the MCP transports' default timeouts.

    The client uses a 30-second timeout for connect/write/pool and a 300-second
    read timeout, because a server may hold a response stream open. Redirect
    following is left at the httpx2 default (off): the MCP transports follow
    redirects within the endpoint's origin themselves, see `stream_within_origin`.

    Args:
        headers: Optional headers to include with all requests.
        timeout: Request timeout as httpx2.Timeout object. Defaults to 30s for
            connect/write/pool and 300s for read (for long-lived SSE streams).
        auth: Optional authentication handler.

    Returns:
        Configured httpx2.AsyncClient instance.

    Note:
        The returned AsyncClient must be used as a context manager to ensure
        proper cleanup of connections.
    """
    if timeout is None:
        timeout = httpx2.Timeout(MCP_DEFAULT_TIMEOUT, read=MCP_DEFAULT_SSE_READ_TIMEOUT)
    kwargs: dict[str, Any] = {"timeout": timeout}
    if headers is not None:
        kwargs["headers"] = headers
    if auth is not None:  # pragma: no cover
        kwargs["auth"] = auth
    return httpx2.AsyncClient(**kwargs)


def _within_origin(url: httpx2.URL, location: httpx2.URL) -> bool:
    """Whether `location` is on `url`'s origin, or is its https upgrade on the default ports.

    httpx2 normalises a scheme's default port to None and lower-cases hosts, so
    plain tuple comparison is exact. The upgrade rule is the one httpx2 itself
    uses to decide a redirect has not left the origin (`_is_https_redirect`).
    """
    if (url.scheme, url.host, url.port) == (location.scheme, location.host, location.port):
        return True
    return (
        url.host == location.host
        and url.scheme == "http"
        and url.port is None
        and location.scheme == "https"
        and location.port is None
    )


@asynccontextmanager
async def stream_within_origin(
    client: httpx2.AsyncClient, method: str, url: httpx2.URL | str, **kwargs: Any
) -> AsyncIterator[httpx2.Response]:
    """`client.stream(...)`, following redirects only while they stay within the request's origin.

    An MCP transport talks to one configured endpoint, and everything on a request
    (headers, auth, body) was configured for that endpoint. A redirect that stays
    on the origin of the request just sent (same scheme, host and port, or http to
    https on the same host with default ports), such as a trailing-slash
    normalisation, is followed using httpx2's own next-request rules. A redirect
    anywhere else is not followed: the redirect response itself is yielded, the
    way httpx2 hands one back when `follow_redirects` is off, and the caller
    treats it as the non-success it is. The client's own `follow_redirects`
    setting is not consulted, and requests an `httpx2.Auth` flow makes during
    the call are sent the same way, so they do not follow redirects either.

    Raises:
        httpx2.TooManyRedirects: More than `client.max_redirects` redirects were followed.
    """
    request = client.build_request(method, url, **kwargs)
    for _ in range(client.max_redirects + 1):
        response = await client.send(request, stream=True, follow_redirects=False)
        # Set by httpx2, with its own method/body/header rules, only when the response is a redirect.
        next_request = response.next_request
        if next_request is None or not _within_origin(response.request.url, next_request.url):
            try:
                yield response
            finally:
                await response.aclose()
            return
        try:
            # Drain the redirect body so the connection returns to the pool, as httpx2 does when it follows.
            await response.aread()
        finally:
            await response.aclose()
        request = next_request
    raise httpx2.TooManyRedirects("Exceeded maximum allowed redirects.", request=request)


async def request_within_origin(
    client: httpx2.AsyncClient, method: str, url: httpx2.URL | str, **kwargs: Any
) -> httpx2.Response:
    """`client.request(...)` with the redirect handling of `stream_within_origin`."""
    async with stream_within_origin(client, method, url, **kwargs) as response:
        await response.aread()
    return response


@asynccontextmanager
async def sse_within_origin(
    client: httpx2.AsyncClient, url: httpx2.URL | str, *, headers: dict[str, str] | None = None
) -> AsyncIterator[httpx2.EventSource]:
    """`client.sse(url)` with the redirect handling of `stream_within_origin`."""
    merged = httpx2.Headers(_SSE_HEADERS)
    merged.update(headers or {})
    async with stream_within_origin(client, "GET", url, headers=merged) as response:
        yield httpx2.EventSource(response)
