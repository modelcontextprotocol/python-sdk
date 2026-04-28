"""Tests for httpx utility functions."""

import httpx

from mcp.shared._httpx_utils import create_mcp_http_client


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
