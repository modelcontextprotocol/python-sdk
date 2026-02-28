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


async def test_check_redirect_ignores_redirect_without_next_request():
    """Test that redirect responses without next_request are ignored."""
    response = httpx.Response(
        302,
        headers={"Location": "http://evil.com"},
        request=httpx.Request("GET", "https://example.com"),
    )
    # next_request is None on a manually constructed response
    assert response.next_request is None
    await _check_redirect(response, RedirectPolicy.BLOCK_SCHEME_DOWNGRADE)


# --- BLOCK_SCHEME_DOWNGRADE tests ---


async def test_block_scheme_downgrade_blocks_https_to_http():
    """Test BLOCK_SCHEME_DOWNGRADE blocks HTTPS->HTTP redirect."""
    response = httpx.Response(
        302,
        headers={"Location": "http://evil.com"},
        request=httpx.Request("GET", "https://example.com"),
    )
    response.next_request = httpx.Request("GET", "http://evil.com")

    with pytest.raises(httpx.HTTPStatusError, match="HTTPS-to-HTTP redirect blocked"):
        await _check_redirect(response, RedirectPolicy.BLOCK_SCHEME_DOWNGRADE)


async def test_block_scheme_downgrade_allows_https_to_https():
    """Test BLOCK_SCHEME_DOWNGRADE allows HTTPS->HTTPS redirect."""
    response = httpx.Response(
        302,
        headers={"Location": "https://other.com"},
        request=httpx.Request("GET", "https://example.com"),
    )
    response.next_request = httpx.Request("GET", "https://other.com")
    await _check_redirect(response, RedirectPolicy.BLOCK_SCHEME_DOWNGRADE)


async def test_block_scheme_downgrade_allows_http_to_http():
    """Test BLOCK_SCHEME_DOWNGRADE allows HTTP->HTTP redirect."""
    response = httpx.Response(
        302,
        headers={"Location": "http://other.com"},
        request=httpx.Request("GET", "http://example.com"),
    )
    response.next_request = httpx.Request("GET", "http://other.com")
    await _check_redirect(response, RedirectPolicy.BLOCK_SCHEME_DOWNGRADE)


async def test_block_scheme_downgrade_allows_http_to_https():
    """Test BLOCK_SCHEME_DOWNGRADE allows HTTP->HTTPS upgrade."""
    response = httpx.Response(
        302,
        headers={"Location": "https://other.com"},
        request=httpx.Request("GET", "http://example.com"),
    )
    response.next_request = httpx.Request("GET", "https://other.com")
    await _check_redirect(response, RedirectPolicy.BLOCK_SCHEME_DOWNGRADE)


# --- ENFORCE_HTTPS tests ---


async def test_enforce_https_blocks_http_target():
    """Test ENFORCE_HTTPS blocks any HTTP redirect target."""
    response = httpx.Response(
        302,
        headers={"Location": "http://evil.com"},
        request=httpx.Request("GET", "https://example.com"),
    )
    response.next_request = httpx.Request("GET", "http://evil.com")

    with pytest.raises(httpx.HTTPStatusError, match="Non-HTTPS redirect blocked"):
        await _check_redirect(response, RedirectPolicy.ENFORCE_HTTPS)


async def test_enforce_https_blocks_http_to_http():
    """Test ENFORCE_HTTPS blocks HTTP->HTTP redirect."""
    response = httpx.Response(
        302,
        headers={"Location": "http://other.com"},
        request=httpx.Request("GET", "http://example.com"),
    )
    response.next_request = httpx.Request("GET", "http://other.com")

    with pytest.raises(httpx.HTTPStatusError, match="Non-HTTPS redirect blocked"):
        await _check_redirect(response, RedirectPolicy.ENFORCE_HTTPS)


async def test_enforce_https_allows_https_target():
    """Test ENFORCE_HTTPS allows HTTPS redirect target."""
    response = httpx.Response(
        302,
        headers={"Location": "https://other.com"},
        request=httpx.Request("GET", "https://example.com"),
    )
    response.next_request = httpx.Request("GET", "https://other.com")
    await _check_redirect(response, RedirectPolicy.ENFORCE_HTTPS)


# --- ALLOW_ALL tests ---


async def test_allow_all_permits_https_to_http():
    """Test ALLOW_ALL permits HTTPS->HTTP redirect."""
    response = httpx.Response(
        302,
        headers={"Location": "http://evil.com"},
        request=httpx.Request("GET", "https://example.com"),
    )
    response.next_request = httpx.Request("GET", "http://evil.com")
    await _check_redirect(response, RedirectPolicy.ALLOW_ALL)
