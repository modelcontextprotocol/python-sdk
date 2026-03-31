"""Tests for Content-Type override in streamable HTTP transport.

Verifies that the content_type parameter allows overriding the Content-Type header
to include custom charsets or other attributes.
"""

import pytest
from mcp.client.streamable_http import StreamableHTTPTransport


def test_streamable_http_transport_default_content_type() -> None:
    """Test that the default Content-Type is 'application/json'."""
    transport = StreamableHTTPTransport("http://example.com/mcp")
    headers = transport._prepare_headers()
    assert headers["content-type"] == "application/json"


def test_streamable_http_transport_custom_content_type() -> None:
    """Test that a custom Content-Type with charset can be specified."""
    transport = StreamableHTTPTransport(
        "http://example.com/mcp",
        content_type="application/json; charset=utf-8",
    )
    headers = transport._prepare_headers()
    assert headers["content-type"] == "application/json; charset=utf-8"


def test_streamable_http_transport_content_type_preserved_in_headers() -> None:
    """Test that Content-Type is correctly placed in prepared headers."""
    custom_type = "application/json; charset=utf-8; boundary=npm"
    transport = StreamableHTTPTransport("http://example.com/mcp", content_type=custom_type)
    headers = transport._prepare_headers()
    # The accept header should also be present
    assert "accept" in headers
    assert headers["content-type"] == custom_type
