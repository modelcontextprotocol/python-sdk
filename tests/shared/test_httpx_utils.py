"""Tests for httpx utility functions."""

import httpx

from mcp.shared.httpx_utils import create_mcp_http_client


class TestCreateMcpHttpClient:
    """Test create_mcp_http_client function."""

    def test_default_settings(self):
        """Test that default settings are applied correctly."""
        client = create_mcp_http_client()
        
        # Check follow_redirects is True
        assert client.follow_redirects is True
        
        # Check default timeout is 30 seconds
        assert client.timeout.connect == 30.0
        assert client.timeout.read == 30.0
        assert client.timeout.write == 30.0
        assert client.timeout.pool == 30.0

    def test_custom_parameters(self):
        """Test custom headers and timeout are set correctly."""
        headers = {"Authorization": "Bearer token", "X-Custom": "value"}
        timeout = httpx.Timeout(connect=5.0, read=10.0, write=15.0, pool=20.0)
        
        client = create_mcp_http_client(headers=headers, timeout=timeout)
        
        # Check headers
        assert client.headers["Authorization"] == "Bearer token"
        assert client.headers["X-Custom"] == "value"
        
        # Check custom timeout
        assert client.timeout.connect == 5.0
        assert client.timeout.read == 10.0
        assert client.timeout.write == 15.0
        assert client.timeout.pool == 20.0

    def test_follow_redirects_enforced(self):
        """Test follow_redirects is always True even if False is passed."""
        client = create_mcp_http_client(follow_redirects=False)
        
        # Should still be True because our defaults override user input
        assert client.follow_redirects is True