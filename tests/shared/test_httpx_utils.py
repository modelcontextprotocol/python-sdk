"""Tests for httpx utility functions."""

import httpx
import pytest

from mcp.shared._httpx_utils import RedirectPolicy, _check_redirect, create_mcp_http_client

pytestmark = pytest.mark.anyio


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


def test_default_redirect_policy():
    """Test that the default redirect policy is BLOCK_SCHEME_DOWNGRADE."""
    client = create_mcp_http_client()
    # Event hooks should be installed for the default policy
    assert len(client.event_hooks["response"]) == 1


def test_allow_all_policy_no_hooks():
    """Test that ALLOW_ALL does not install event hooks."""
    client = create_mcp_http_client(redirect_policy=RedirectPolicy.ALLOW_ALL)
    assert len(client.event_hooks["response"]) == 0


# --- _check_redirect unit tests ---


async def test_check_redirect_ignores_non_redirect():
    """Test that non-redirect responses are ignored."""
    response = httpx.Response(200, request=httpx.Request("GET", "https://example.com"))
    # Should not raise
    await _check_redirect(response, RedirectPolicy.BLOCK_SCHEME_DOWNGRADE)
    await _check_redirect(response, RedirectPolicy.ENFORCE_HTTPS)


async def test_check_redirect_ignores_redirect_without_location_header():
    """Test that redirect responses without a Location header are ignored."""
    response = httpx.Response(
        302,
        request=httpx.Request("GET", "https://example.com"),
    )
    # No Location header → has_redirect_location is False
    assert not response.has_redirect_location
    await _check_redirect(response, RedirectPolicy.BLOCK_SCHEME_DOWNGRADE)


# --- BLOCK_SCHEME_DOWNGRADE tests ---


async def test_block_scheme_downgrade_blocks_https_to_http():
    """Test BLOCK_SCHEME_DOWNGRADE blocks HTTPS->HTTP redirect."""
    response = httpx.Response(
        302,
        headers={"Location": "http://evil.com"},
        request=httpx.Request("GET", "https://example.com"),
    )

    with pytest.raises(httpx.HTTPStatusError, match="HTTPS-to-HTTP redirect blocked"):
        await _check_redirect(response, RedirectPolicy.BLOCK_SCHEME_DOWNGRADE)


async def test_block_scheme_downgrade_allows_https_to_https():
    """Test BLOCK_SCHEME_DOWNGRADE allows HTTPS->HTTPS redirect."""
    response = httpx.Response(
        302,
        headers={"Location": "https://other.com"},
        request=httpx.Request("GET", "https://example.com"),
    )
    await _check_redirect(response, RedirectPolicy.BLOCK_SCHEME_DOWNGRADE)


async def test_block_scheme_downgrade_allows_http_to_http():
    """Test BLOCK_SCHEME_DOWNGRADE allows HTTP->HTTP redirect."""
    response = httpx.Response(
        302,
        headers={"Location": "http://other.com"},
        request=httpx.Request("GET", "http://example.com"),
    )
    await _check_redirect(response, RedirectPolicy.BLOCK_SCHEME_DOWNGRADE)


async def test_block_scheme_downgrade_allows_http_to_https():
    """Test BLOCK_SCHEME_DOWNGRADE allows HTTP->HTTPS upgrade."""
    response = httpx.Response(
        302,
        headers={"Location": "https://other.com"},
        request=httpx.Request("GET", "http://example.com"),
    )
    await _check_redirect(response, RedirectPolicy.BLOCK_SCHEME_DOWNGRADE)


async def test_block_scheme_downgrade_allows_relative_redirect():
    """Test BLOCK_SCHEME_DOWNGRADE allows relative Location headers."""
    response = httpx.Response(
        302,
        headers={"Location": "/other-path"},
        request=httpx.Request("GET", "https://example.com/start"),
    )
    await _check_redirect(response, RedirectPolicy.BLOCK_SCHEME_DOWNGRADE)


# --- ENFORCE_HTTPS tests ---


async def test_enforce_https_blocks_http_target():
    """Test ENFORCE_HTTPS blocks any HTTP redirect target."""
    response = httpx.Response(
        302,
        headers={"Location": "http://evil.com"},
        request=httpx.Request("GET", "https://example.com"),
    )

    with pytest.raises(httpx.HTTPStatusError, match="Non-HTTPS redirect blocked"):
        await _check_redirect(response, RedirectPolicy.ENFORCE_HTTPS)


async def test_enforce_https_blocks_http_to_http():
    """Test ENFORCE_HTTPS blocks HTTP->HTTP redirect."""
    response = httpx.Response(
        302,
        headers={"Location": "http://other.com"},
        request=httpx.Request("GET", "http://example.com"),
    )

    with pytest.raises(httpx.HTTPStatusError, match="Non-HTTPS redirect blocked"):
        await _check_redirect(response, RedirectPolicy.ENFORCE_HTTPS)


async def test_enforce_https_allows_https_target():
    """Test ENFORCE_HTTPS allows HTTPS redirect target."""
    response = httpx.Response(
        302,
        headers={"Location": "https://other.com"},
        request=httpx.Request("GET", "https://example.com"),
    )
    await _check_redirect(response, RedirectPolicy.ENFORCE_HTTPS)


# --- ALLOW_ALL tests ---


async def test_allow_all_permits_https_to_http():
    """Test ALLOW_ALL permits HTTPS->HTTP redirect."""
    response = httpx.Response(
        302,
        headers={"Location": "http://evil.com"},
        request=httpx.Request("GET", "https://example.com"),
    )
    await _check_redirect(response, RedirectPolicy.ALLOW_ALL)


# --- Integration tests (exercise the event hook wiring end-to-end) ---


async def test_redirect_hook_blocks_scheme_downgrade_via_transport():
    """Test that the event hook installed by create_mcp_http_client blocks HTTPS->HTTP."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.com/start":
            return httpx.Response(302, headers={"Location": "http://evil.com/stolen"})
        return httpx.Response(200, text="OK")  # pragma: no cover

    async with create_mcp_http_client() as client:
        client._transport = httpx.MockTransport(mock_handler)

        with pytest.raises(httpx.HTTPStatusError, match="HTTPS-to-HTTP redirect blocked"):
            await client.get("https://example.com/start")


async def test_redirect_hook_allows_safe_redirect_via_transport():
    """Test that the event hook allows HTTPS->HTTPS redirects through the client."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.com/start":
            return httpx.Response(302, headers={"Location": "https://example.com/final"})
        return httpx.Response(200, text="OK")

    async with create_mcp_http_client() as client:
        client._transport = httpx.MockTransport(mock_handler)

        response = await client.get("https://example.com/start")
        assert response.status_code == 200
