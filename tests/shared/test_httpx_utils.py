"""Tests for the httpx2 helpers the client transports are built on."""

from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

import httpx2
import pytest

from mcp.shared._httpx_utils import (
    create_mcp_http_client,
    request_within_origin,
    sse_within_origin,
    stream_within_origin,
)

pytestmark = pytest.mark.anyio


def test_default_client_uses_mcp_timeouts_and_httpx_redirect_default():
    """The factory applies the transports' timeouts and leaves redirect following to the transports."""
    client = create_mcp_http_client()

    assert client.follow_redirects is False
    assert client.timeout == httpx2.Timeout(30.0, read=300.0)


def test_custom_parameters():
    """Test custom headers and timeout are set correctly."""
    headers = {"Authorization": "Bearer token"}
    timeout = httpx2.Timeout(60.0)

    client = create_mcp_http_client(headers, timeout)

    assert client.headers["Authorization"] == "Bearer token"
    assert client.timeout.connect == 60.0


class _Body(httpx2.AsyncByteStream):
    """A response body served as a real stream, recording whether the client closed it."""

    def __init__(self, data: bytes, closed: list[bool]) -> None:
        self._data = data
        self._closed = closed

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._data

    async def aclose(self) -> None:
        self._closed.append(True)


def _recording_client(
    redirects: dict[str, tuple[int, str]], **client_kwargs: Any
) -> tuple[httpx2.AsyncClient, list[str], list[bool]]:
    """A client whose server redirects each URL in `redirects` (status, Location) and answers 200
    to anything else; plus the `METHOD url` lines the server received and one entry per redirect
    response body the client closed."""
    received: list[str] = []
    closed: list[bool] = []

    def serve(request: httpx2.Request) -> httpx2.Response:
        received.append(f"{request.method} {request.url}")
        if str(request.url) in redirects:
            status, location = redirects[str(request.url)]
            return httpx2.Response(status, headers={"location": location}, stream=_Body(b"moved", closed))
        return httpx2.Response(200, text=request.content.decode() or "ok")

    return httpx2.AsyncClient(transport=httpx2.MockTransport(serve), **client_kwargs), received, closed


@pytest.mark.parametrize(
    ("url", "location"),
    [
        ("http://mcp.example/mcp", "http://mcp.example/mcp/"),
        ("http://mcp.example/mcp", "/other/path"),
        ("http://mcp.example:8080/mcp", "http://mcp.example:8080/v2/mcp"),
        ("http://mcp.example/mcp", "http://MCP.EXAMPLE:80/mcp/"),
        ("http://mcp.example/mcp", "https://mcp.example:443/mcp"),
    ],
)
async def test_redirect_within_origin_is_followed_with_method_and_body(url: str, location: str):
    """A redirect that stays on the request's origin (or upgrades it to https) is followed, and a
    307 keeps the method and body (SDK-defined policy; the re-send itself is httpx2's)."""
    client, received, closed = _recording_client({url: (307, location)})

    async with client, stream_within_origin(client, "POST", url, content=b"payload") as response:
        await response.aread()

    assert response.status_code == 200
    assert response.text == "payload"
    assert received == [f"POST {url}", f"POST {httpx2.URL(url).join(location)}"]
    assert closed == [True]


@pytest.mark.parametrize(
    "location",
    [
        "http://other.example/mcp",
        "http://mcp.example:8080/mcp",
        "http://sub.mcp.example/mcp",
        "https://mcp.example:8443/mcp",
        "ftp://mcp.example/mcp",
    ],
)
async def test_redirect_outside_origin_is_not_followed(location: str):
    """A redirect to another origin is handed back unfollowed, the way httpx2 hands back a redirect
    with following off, and the location is never requested (SDK-defined policy)."""
    url = "http://mcp.example/mcp"
    client, received, closed = _recording_client({url: (307, location)})

    async with client, stream_within_origin(client, "POST", url, content=b"payload") as response:
        pass

    assert response.status_code == 307
    assert response.next_request is not None
    assert response.next_request.url == location
    assert received == [f"POST {url}"]
    assert closed == [True]


@pytest.mark.parametrize("status", [301, 302, 303])
async def test_method_changing_redirect_of_a_post_is_not_followed(status: int):
    """httpx2 turns a POST into a body-less GET for 301/302/303, which would drop the message, so a
    same-origin redirect with one of those codes is handed back unfollowed (SDK-defined)."""
    url = "http://mcp.example/mcp"
    client, received, _ = _recording_client({url: (status, "/mcp/")})

    async with client, stream_within_origin(client, "POST", url, content=b"payload") as response:
        pass

    assert response.status_code == status
    assert received == [f"POST {url}"]


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_same_origin_redirect_of_a_get_is_followed_for_every_redirect_status(status: int):
    """A GET keeps its method under every redirect status, so the SSE GET follows all of them
    within the origin (SDK-defined policy over httpx2's method rules)."""
    url = "http://mcp.example/sse"
    client, received, _ = _recording_client({url: (status, "/sse/")})

    async with client, stream_within_origin(client, "GET", url) as response:
        await response.aread()

    assert response.status_code == 200
    assert received == [f"GET {url}", "GET http://mcp.example/sse/"]


async def test_https_to_http_on_same_host_is_outside_origin():
    """Only the upgrade direction counts as staying on the origin; a downgrade is not followed."""
    url = "https://mcp.example/mcp"
    client, received, _ = _recording_client({url: (302, "http://mcp.example/mcp")})

    async with client, stream_within_origin(client, "GET", url) as response:
        pass

    assert response.status_code == 302
    assert received == [f"GET {url}"]


async def test_client_configured_to_follow_redirects_is_still_scoped_to_origin():
    """The client's own follow_redirects=True does not widen the policy: the transport helper
    decides per request (SDK-defined)."""
    url = "http://mcp.example/mcp"
    client, received, _ = _recording_client({url: (307, "http://other.example/mcp")}, follow_redirects=True)

    async with client, stream_within_origin(client, "POST", url) as response:
        pass

    assert response.status_code == 307
    assert received == [f"POST {url}"]


async def test_redirect_past_the_client_max_redirects_budget_is_handed_back_unfollowed():
    """Same-origin hops are bounded by the client's max_redirects; the redirect after that is not
    followed but handed back like any other, so a loop fails the one call rather than raising
    (SDK-defined; max_redirects=0 therefore means "follow none")."""
    url = "http://mcp.example/a"
    client, received, closed = _recording_client(
        {
            "http://mcp.example/a": (307, "/b"),
            "http://mcp.example/b": (307, "/c"),
            "http://mcp.example/c": (307, "/d"),
        },
        max_redirects=2,
    )

    async with client:
        response = await request_within_origin(client, "GET", url)

    assert response.status_code == 307
    assert response.next_request is not None
    assert response.next_request.url == "http://mcp.example/d"
    assert received == ["GET http://mcp.example/a", "GET http://mcp.example/b", "GET http://mcp.example/c"]
    assert closed == [True, True, True]


async def test_redirect_location_with_userinfo_is_not_followed():
    """A Location carrying user:password is handed back unfollowed even within the origin, since
    httpx2 would otherwise send that userinfo as Basic auth (SDK-defined)."""
    url = "http://mcp.example/mcp"
    client, received, _ = _recording_client({url: (307, "http://user:secret@mcp.example/mcp/")})

    async with client, stream_within_origin(client, "POST", url) as response:
        pass

    assert response.status_code == 307
    assert received == [f"POST {url}"]


async def test_userinfo_of_the_configured_url_kept_by_a_relative_location_is_followed():
    """Userinfo the caller put in the endpoint URL is carried over by a relative Location (URL join
    keeps the authority); that is the caller's own credential for the same origin, so the redirect
    is followed as httpx2 itself would (SDK-defined)."""
    url = "http://user:secret@mcp.example/mcp"
    client, received, _ = _recording_client({url: (307, "/mcp/")})

    async with client, stream_within_origin(client, "POST", url, content=b"payload") as response:
        await response.aread()

    assert response.status_code == 200
    assert received == [f"POST {url}", "POST http://user:secret@mcp.example/mcp/"]


async def test_request_within_origin_returns_a_read_response():
    """The non-streaming form hands back a response whose body is already read."""
    url = "http://mcp.example/mcp"
    client, received, _ = _recording_client({url: (307, "/mcp/")})

    async with client:
        response = await request_within_origin(client, "DELETE", url)

    assert response.status_code == 200
    assert response.text == "ok"
    assert received == [f"DELETE {url}", "DELETE http://mcp.example/mcp/"]


async def test_sse_within_origin_sends_event_stream_headers_and_caller_headers():
    """The SSE form asks for an event stream exactly as client.sse() does, merged case-insensitively
    with the caller's headers, and yields an EventSource over the final response."""
    seen: list[httpx2.Headers] = []

    def serve(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, text="data: hello\n\n")

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(serve))
    async with client:
        async with sse_within_origin(client, "http://mcp.example/sse") as source:
            events = [event.data async for event in source]
        async with sse_within_origin(client, "http://mcp.example/sse", headers={"accept": "x/y", "k": "v"}):
            pass

    assert events == ["hello"]
    assert seen[0]["accept"] == "text/event-stream"
    assert seen[0]["cache-control"] == "no-store"
    assert seen[1].get_list("accept") == ["x/y"]
    assert seen[1]["cache-control"] == "no-store"
    assert seen[1]["k"] == "v"


async def test_auth_flow_requests_are_not_redirected():
    """Requests an httpx2 Auth flow issues while a transport request is in flight (a token refresh,
    say) inherit the per-request no-follow setting, so a redirect on them is handed back to the
    auth flow rather than followed (httpx2 behaviour the transports rely on)."""
    received: list[str] = []

    class TokenThenRequest(httpx2.Auth):
        async def async_auth_flow(self, request: httpx2.Request) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
            token_response = yield httpx2.Request("POST", "http://mcp.example/token", content=b"grant")
            request.headers["x-token-status"] = str(token_response.status_code)
            yield request

    def serve(request: httpx2.Request) -> httpx2.Response:
        received.append(f"{request.method} {request.url}")
        if request.url.path == "/token":
            return httpx2.Response(307, headers={"location": "http://other.example/token"})
        return httpx2.Response(200, text=request.headers["x-token-status"])

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(serve), auth=TokenThenRequest(), follow_redirects=True)
    async with client:
        response = await request_within_origin(client, "POST", "http://mcp.example/mcp")

    assert response.text == "307"
    assert received == ["POST http://mcp.example/token", "POST http://mcp.example/mcp"]
