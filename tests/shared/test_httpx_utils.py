"""Tests for httpx2 utility functions."""

import httpx2

from mcp.shared._httpx_utils import create_mcp_http_client


def test_default_settings():
    """Test that default settings are applied correctly."""
    client = create_mcp_http_client()

    assert client.follow_redirects is True
    assert client.timeout.connect == 30.0


def test_custom_parameters():
    """Test custom headers and timeout are set correctly."""
    headers = {"Authorization": "Bearer token"}
    timeout = httpx2.Timeout(60.0)

    client = create_mcp_http_client(headers, timeout)

    assert client.headers["Authorization"] == "Bearer token"
    assert client.timeout.connect == 60.0


def test_public_reexport_from_streamable_http():
    """The factory, protocol, and timeout defaults are importable from the
    public ``mcp.client.streamable_http`` module, not only the private
    ``mcp.shared._httpx_utils``."""
    import mcp.shared._httpx_utils as private_module
    from mcp.client import streamable_http

    assert streamable_http.create_mcp_http_client is private_module.create_mcp_http_client
    assert streamable_http.McpHttpClientFactory is private_module.McpHttpClientFactory
    assert streamable_http.MCP_DEFAULT_TIMEOUT == private_module.MCP_DEFAULT_TIMEOUT
    assert streamable_http.MCP_DEFAULT_SSE_READ_TIMEOUT == private_module.MCP_DEFAULT_SSE_READ_TIMEOUT
