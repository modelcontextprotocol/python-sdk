"""Tests for httpx utility functions."""

import httpx
import pytest

from mcp.shared._httpx_utils import RedirectError, _resolve_redirect_target, create_mcp_http_client, redirect_error


@pytest.fixture(autouse=True)
def _no_proxy_env(no_proxy_env: None) -> None:
    """Every test here swaps a mock transport into a factory-built client."""


def test_default_settings():
    """Test that default settings are applied correctly."""
    client = create_mcp_http_client()

    assert client.follow_redirects is True
    assert client.timeout.connect == 30.0


def test_custom_parameters():
    """Test custom headers and timeout are set correctly."""
    headers = {"Authorization": "Bearer token"}
    timeout = httpx.Timeout(60.0)

    client = create_mcp_http_client(headers, timeout)

    assert client.headers["Authorization"] == "Bearer token"
    assert client.timeout.connect == 60.0


def _redirecting_transport(location: str, requests: list[httpx.Request]) -> httpx.MockTransport:
    """First request gets a 307 to `location`; every request is recorded."""

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(307, headers={"location": location})
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handle)


@pytest.mark.anyio
async def test_follows_same_origin_redirect():
    requests: list[httpx.Request] = []
    transport = _redirecting_transport("/canonical", requests)
    client = create_mcp_http_client(headers={"X-Custom": "value"})
    client._transport = transport  # swap in the mock transport

    response = await client.post("http://example.com/endpoint", content=b"payload")

    assert response.status_code == 200
    assert len(requests) == 2
    assert requests[1].url == httpx.URL("http://example.com/canonical")
    assert requests[1].method == "POST"
    assert requests[1].headers["X-Custom"] == "value"
    assert requests[1].content == b"payload"
    await client.aclose()


@pytest.mark.anyio
async def test_follows_https_upgrade_redirect():
    requests: list[httpx.Request] = []
    transport = _redirecting_transport("https://example.com/endpoint", requests)
    client = create_mcp_http_client()
    client._transport = transport

    response = await client.get("http://example.com/endpoint")

    assert response.status_code == 200
    assert len(requests) == 2
    assert requests[1].url == httpx.URL("https://example.com/endpoint")
    await client.aclose()


@pytest.mark.anyio
async def test_rejects_redirect_to_other_host():
    requests: list[httpx.Request] = []
    transport = _redirecting_transport("https://other.example.com/collect", requests)
    client = create_mcp_http_client(headers={"X-Custom": "value"})
    client._transport = transport

    with pytest.raises(RedirectError) as excinfo:
        await client.post("https://example.com/endpoint", content=b"payload")

    # The redirect was not followed: exactly one request went out.
    assert len(requests) == 1
    assert "https://other.example.com/collect" in str(excinfo.value)
    assert "different origin" in str(excinfo.value)
    await client.aclose()


@pytest.mark.anyio
async def test_rejects_redirect_to_other_port():
    requests: list[httpx.Request] = []
    transport = _redirecting_transport("http://example.com:9000/endpoint", requests)
    client = create_mcp_http_client()
    client._transport = transport

    with pytest.raises(RedirectError):
        await client.get("http://example.com:8000/endpoint")

    assert len(requests) == 1
    await client.aclose()


@pytest.mark.anyio
async def test_rejects_https_to_http_redirect():
    requests: list[httpx.Request] = []
    transport = _redirecting_transport("http://example.com/endpoint", requests)
    client = create_mcp_http_client()
    client._transport = transport

    with pytest.raises(RedirectError):
        await client.get("https://example.com/endpoint")

    assert len(requests) == 1
    await client.aclose()


@pytest.mark.anyio
async def test_rejects_absolute_form_location_without_host():
    # An "absolute" Location with no host keeps the request's host but not its
    # port (matching httpx's own resolution), so from a non-default port this
    # resolves to a different origin and is refused.
    requests: list[httpx.Request] = []
    transport = _redirecting_transport("http:///moved", requests)
    client = create_mcp_http_client()
    client._transport = transport

    with pytest.raises(RedirectError) as excinfo:
        await client.get("http://example.com:8000/endpoint")

    assert len(requests) == 1
    assert "http://example.com/moved" in str(excinfo.value)
    await client.aclose()


@pytest.mark.anyio
async def test_unparsable_location_defers_to_httpx():
    requests: list[httpx.Request] = []
    transport = _redirecting_transport("http://\x00bad/", requests)
    client = create_mcp_http_client()
    client._transport = transport

    with pytest.raises(httpx.RemoteProtocolError):
        await client.get("https://example.com/endpoint")

    await client.aclose()


@pytest.mark.anyio
async def test_user_supplied_client_still_follows_everything():
    """A caller's own follow_redirects=True client is not policed by the SDK."""
    requests: list[httpx.Request] = []
    transport = _redirecting_transport("https://other.example.com/moved", requests)

    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        response = await client.get("https://example.com/endpoint")

    assert response.status_code == 200
    assert len(requests) == 2
    assert requests[1].url == httpx.URL("https://other.example.com/moved")


def test_redirect_error_builder_same_origin_names_target():
    request = httpx.Request("POST", "http://example.com/endpoint")
    response = httpx.Response(307, headers={"location": "/canonical"}, request=request)

    error = redirect_error(response)

    assert "http://example.com/canonical" in str(error)
    assert "Connect to that URL directly" in str(error)


def test_redirect_error_builder_includes_context():
    request = httpx.Request("POST", "https://auth.example.com/token")
    response = httpx.Response(307, headers={"location": "https://other.example.com/token"}, request=request)

    error = redirect_error(response, context="OAuth token request")

    assert str(error).startswith("OAuth token request: ")
    assert "different origin" in str(error)


def test_redirect_error_builder_unparsable_location():
    request = httpx.Request("GET", "https://example.com/endpoint")
    response = httpx.Response(307, headers={"location": "http://\x00bad/"}, request=request)

    error = redirect_error(response)

    assert "unparsable Location" in str(error)


def test_redirect_error_is_httpx_status_error():
    """Existing handlers that catch httpx.HTTPStatusError keep working."""
    request = httpx.Request("GET", "https://example.com/endpoint")
    response = httpx.Response(307, headers={"location": "https://other.example.com/"}, request=request)

    assert isinstance(redirect_error(response), httpx.HTTPStatusError)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "location",
    [
        "/relative/path?q=1",
        "relative-no-slash",
        "http:///absolute-form-no-host",
        "https://other.example.com/absolute",
        "//protocol-relative.example.com/x",
        "http://example.com:8000/same-origin",
    ],
)
async def test_redirect_target_resolution_matches_httpx(location: str) -> None:
    """The policy must judge exactly the URL httpx itself would follow.

    Guards against drift between _resolve_redirect_target and httpx's own
    redirect URL construction across httpx upgrades.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"location": location})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        response = await client.get("http://example.com:8000/base/path")

    assert response.next_request is not None
    assert _resolve_redirect_target(response.request.url, location) == response.next_request.url
