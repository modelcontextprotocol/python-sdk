"""Utilities for creating and using httpx AsyncClient instances in the MCP transports."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, Protocol

import httpx
from httpx_sse import EventSource

__all__ = ["create_mcp_http_client", "MCP_DEFAULT_TIMEOUT", "MCP_DEFAULT_SSE_READ_TIMEOUT"]

# Default MCP timeout configuration
MCP_DEFAULT_TIMEOUT = 30.0  # General operations (seconds)
MCP_DEFAULT_SSE_READ_TIMEOUT = 300.0  # SSE streams - 5 minutes (seconds)

# The headers httpx_sse.aconnect_sse() adds to an event-stream request.
_SSE_HEADERS = {"Accept": "text/event-stream", "Cache-Control": "no-store"}

# How many redirects one auth-flow request may follow within its origin (see RedirectAwareAuth).
_AUTH_REDIRECT_LIMIT = 5


class McpHttpClientFactory(Protocol):  # pragma: no branch
    def __call__(  # pragma: no branch
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient: ...


def create_mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """Create an httpx AsyncClient with the MCP transports' default timeouts.

    The client uses a 30-second timeout for connect/write/pool and a 300-second
    read timeout, because a server may hold a response stream open. Redirect
    following is left at the httpx default (off): the MCP transports follow
    redirects within the endpoint's origin themselves, see `stream_within_origin`.

    Args:
        headers: Optional headers to include with all requests.
        timeout: Request timeout as httpx.Timeout object. Defaults to 30s for
            connect/write/pool and 300s for read (for long-lived SSE streams).
        auth: Optional authentication handler.

    Returns:
        Configured httpx.AsyncClient instance.

    Note:
        The returned AsyncClient must be used as a context manager to ensure
        proper cleanup of connections.
    """
    if timeout is None:
        timeout = httpx.Timeout(MCP_DEFAULT_TIMEOUT, read=MCP_DEFAULT_SSE_READ_TIMEOUT)
    kwargs: dict[str, Any] = {"timeout": timeout}
    if headers is not None:
        kwargs["headers"] = headers
    if auth is not None:  # pragma: no cover
        kwargs["auth"] = auth
    return httpx.AsyncClient(**kwargs)


def _within_origin(url: httpx.URL, location: httpx.URL) -> bool:
    """Whether `location` is on `url`'s origin, or is its https upgrade on the default ports.

    httpx normalises a scheme's default port to None and lower-cases hosts, so
    plain tuple comparison is exact. The upgrade rule is the one httpx itself
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


def next_request_within_origin(response: httpx.Response) -> httpx.Request | None:
    """The request that follows `response`'s redirect, if it is one the MCP transports follow.

    That is when httpx built a next request for it (a redirect status with a
    Location), the next request keeps the method (307/308, or any redirect of a
    GET: httpx turns a POST into a body-less GET for 301/302/303, which would
    drop the message), its URL stays within the origin of the request just sent
    (same scheme, host and port, or http to https on the same host with default
    ports), and the Location carries no userinfo (which httpx would otherwise
    send as Basic auth). None for anything else, including a non-redirect.
    """
    next_request = response.next_request
    if next_request is None:
        return None
    sent = response.request
    if (
        next_request.method != sent.method
        or next_request.url.userinfo
        or not _within_origin(sent.url, next_request.url)
    ):
        return None
    return next_request


@asynccontextmanager
async def stream_within_origin(
    client: httpx.AsyncClient, method: str, url: httpx.URL | str, **kwargs: Any
) -> AsyncGenerator[httpx.Response, None]:
    """`client.stream(...)`, following redirects only while they stay within the request's origin.

    An MCP transport talks to one configured endpoint, and everything on a request
    (headers, auth, body) was configured for that endpoint. A redirect that
    `next_request_within_origin` accepts, such as a 307/308 trailing-slash
    normalisation, is followed, at most `client.max_redirects` times. Any other
    redirect (or one past that budget) is not followed: the redirect response
    itself is yielded, the way httpx hands one back when `follow_redirects` is
    off, and the caller treats it as the non-success it is. The client's own
    `follow_redirects` setting is not consulted. Requests an `httpx.Auth` flow
    makes during the call are sent without following either; the SDK's OAuth
    providers apply the same rule to their own requests.
    """
    request = client.build_request(method, url, **kwargs)
    followed = 0
    while True:
        response = await client.send(request, stream=True, follow_redirects=False)
        next_request = next_request_within_origin(response)
        if next_request is None or followed == client.max_redirects:
            break
        try:
            # Drain the redirect body so the connection returns to the pool, as httpx does when it follows.
            await response.aread()
        finally:
            await response.aclose()
        request = next_request
        followed += 1
    try:
        yield response
    finally:
        await response.aclose()


async def request_within_origin(
    client: httpx.AsyncClient, method: str, url: httpx.URL | str, **kwargs: Any
) -> httpx.Response:
    """`client.request(...)` with the redirect handling of `stream_within_origin`."""
    async with stream_within_origin(client, method, url, **kwargs) as response:
        await response.aread()
    return response


@asynccontextmanager
async def sse_within_origin(
    client: httpx.AsyncClient, url: httpx.URL | str, *, headers: dict[str, str] | None = None
) -> AsyncGenerator[EventSource, None]:
    """`httpx_sse.aconnect_sse(client, "GET", url)` with the redirect handling of `stream_within_origin`."""
    merged = httpx.Headers(_SSE_HEADERS)
    merged.update(headers or {})
    async with stream_within_origin(client, "GET", url, headers=merged) as response:
        yield EventSource(response)


def redirect_location(response: httpx.Response) -> httpx.URL | None:
    """Where `response` redirects to, for use in a message: without userinfo, query or fragment,
    which can carry state that does not belong in an error or a log line. None if not a redirect."""
    if response.next_request is None:
        return None
    return response.next_request.url.copy_with(userinfo=b"", query=None, fragment=None)


def redirect_note(response: httpx.Response) -> str:
    """A suffix naming the location of a redirect response that was not followed, else empty."""
    location = redirect_location(response)
    if location is None:
        return ""
    return f" (redirected to {location}; not followed)"


class RedirectAwareAuth(ABC, httpx.Auth):
    """An `httpx.Auth` whose own requests follow redirects the way MCP transport requests do.

    The transports send every request with redirect following off and follow a
    redirect themselves only within the endpoint's origin (`stream_within_origin`).
    httpx applies that per-request setting to the requests an auth flow makes
    too (metadata discovery, registration, token), so on their own those would
    follow nothing. Subclasses write their flow as `_auth_flow`; this class
    drives it and, for each request the flow makes other than the one being
    authenticated, follows a redirect that `next_request_within_origin` accepts,
    up to `_AUTH_REDIRECT_LIMIT` times. Any other redirect response is handed
    to the flow as it is.
    """

    @abstractmethod
    def _auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """The subclass's flow, written as `httpx.Auth.async_auth_flow` otherwise would be."""

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        flow = self._auth_flow(request)
        try:
            outgoing = await flow.__anext__()
            while True:
                response = yield outgoing
                if outgoing is not request:
                    for _ in range(_AUTH_REDIRECT_LIMIT):
                        follow = next_request_within_origin(response)
                        if follow is None:
                            break
                        response = yield follow
                outgoing = await flow.asend(response)
        except StopAsyncIteration:
            return
        finally:
            await flow.aclose()
