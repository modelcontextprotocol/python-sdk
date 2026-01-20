"""Tests for transport type inference."""

import pytest

from mcp.client.client import _infer_transport
from mcp.client.transports import HttpTransport, InMemoryTransport, SSETransport, Transport
from mcp.server import Server
from mcp.server.fastmcp import FastMCP


def test_infer_transport_from_server():
    """Test that Server instances are wrapped in InMemoryTransport."""
    server = Server(name="test")
    transport = _infer_transport(server)

    assert isinstance(transport, InMemoryTransport)


def test_infer_transport_from_fastmcp():
    """Test that FastMCP instances are wrapped in InMemoryTransport."""
    server = FastMCP("test")
    transport = _infer_transport(server)

    assert isinstance(transport, InMemoryTransport)


def test_infer_transport_from_url_string():
    """Test that URL strings are wrapped in HttpTransport."""
    transport = _infer_transport("http://localhost:8000/mcp")

    assert isinstance(transport, HttpTransport)


def test_infer_transport_from_https_url():
    """Test that HTTPS URLs are wrapped in HttpTransport."""
    transport = _infer_transport("https://example.com/mcp")

    assert isinstance(transport, HttpTransport)


def test_infer_transport_passthrough_http():
    """Test that HttpTransport instances are passed through unchanged."""
    original = HttpTransport("http://localhost:8000/mcp")
    transport = _infer_transport(original)

    assert transport is original


def test_infer_transport_passthrough_sse():
    """Test that SSETransport instances are passed through unchanged."""
    original = SSETransport("http://localhost:8000/sse")
    transport = _infer_transport(original)

    assert transport is original


def test_infer_transport_passthrough_memory():
    """Test that InMemoryTransport instances are passed through unchanged."""
    server = FastMCP("test")
    original = InMemoryTransport(server)
    transport = _infer_transport(original)

    assert transport is original


def test_infer_transport_invalid_type():
    """Test that invalid types are passed through to HttpTransport.

    Note: After type narrowing (Transport, Server|FastMCP), remaining types
    are treated as URL strings and passed to HttpTransport. This means
    invalid types will fail at HttpTransport construction time, not in
    _infer_transport itself.
    """
    # Invalid types are treated as URL strings and passed to HttpTransport
    # HttpTransport will accept any string-like input
    transport = _infer_transport(12345)  # type: ignore[arg-type]
    assert isinstance(transport, HttpTransport)


def test_infer_transport_raise_exceptions_passed_to_memory():
    """Test that raise_exceptions is passed to InMemoryTransport."""
    server = FastMCP("test")
    transport = _infer_transport(server, raise_exceptions=True)

    assert isinstance(transport, InMemoryTransport)
    assert transport._raise_exceptions is True


def test_transport_protocol_compliance():
    """Test that all transport classes implement the Transport protocol."""
    server = FastMCP("test")

    # Check that each transport is recognized as a Transport
    assert isinstance(InMemoryTransport(server), Transport)
    assert isinstance(HttpTransport("http://localhost:8000"), Transport)
    assert isinstance(SSETransport("http://localhost:8000"), Transport)
