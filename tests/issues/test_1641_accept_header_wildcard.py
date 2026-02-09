"""Test for issue #1641 - Accept header wildcard support.

The MCP server was rejecting requests with wildcard Accept headers like `*/*`
or `application/*`, returning 406 Not Acceptable. Per RFC 9110 Section 12.5.1,
wildcard media types are valid and should match the required content types.

These tests verify the `_check_accept_headers` method directly, ensuring
wildcard media types are properly matched against the required content types
(application/json and text/event-stream).
"""

import pytest
from starlette.requests import Request

from mcp.server.streamable_http import StreamableHTTPServerTransport


def _make_request(accept: str) -> Request:
    """Create a minimal Request with the given Accept header."""
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"accept", accept.encode())],
    }
    return Request(scope)


@pytest.mark.anyio
async def test_accept_wildcard_star_star_json_mode():
    """Accept: */* should satisfy application/json requirement."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=True,
    )
    request = _make_request("*/*")
    has_json, has_sse = transport._check_accept_headers(request)
    assert has_json, "*/* should match application/json"
    assert has_sse, "*/* should match text/event-stream"


@pytest.mark.anyio
async def test_accept_wildcard_star_star_sse_mode():
    """Accept: */* should satisfy both JSON and SSE requirements."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=False,
    )
    request = _make_request("*/*")
    has_json, has_sse = transport._check_accept_headers(request)
    assert has_json, "*/* should match application/json"
    assert has_sse, "*/* should match text/event-stream"


@pytest.mark.anyio
async def test_accept_application_wildcard():
    """Accept: application/* should satisfy application/json but not text/event-stream."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=True,
    )
    request = _make_request("application/*")
    has_json, has_sse = transport._check_accept_headers(request)
    assert has_json, "application/* should match application/json"
    assert not has_sse, "application/* should NOT match text/event-stream"


@pytest.mark.anyio
async def test_accept_text_wildcard_with_json():
    """Accept: application/json, text/* should satisfy both requirements in SSE mode."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=False,
    )
    request = _make_request("application/json, text/*")
    has_json, has_sse = transport._check_accept_headers(request)
    assert has_json, "application/json should match JSON content type"
    assert has_sse, "text/* should match text/event-stream"


@pytest.mark.anyio
async def test_accept_wildcard_with_quality_parameter():
    """Accept: */*;q=0.8 should be accepted (quality parameters stripped before matching)."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=True,
    )
    request = _make_request("*/*;q=0.8")
    has_json, has_sse = transport._check_accept_headers(request)
    assert has_json, "*/*;q=0.8 should match application/json after stripping quality"
    assert has_sse, "*/*;q=0.8 should match text/event-stream after stripping quality"


@pytest.mark.anyio
async def test_accept_invalid_still_rejected():
    """Accept: text/plain should not match JSON or SSE content types."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=True,
    )
    request = _make_request("text/plain")
    has_json, has_sse = transport._check_accept_headers(request)
    assert not has_json, "text/plain should NOT match application/json"
    assert not has_sse, "text/plain should NOT match text/event-stream"


@pytest.mark.anyio
async def test_accept_partial_wildcard_sse_mode():
    """Accept: application/* alone should not satisfy SSE requirement."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=False,
    )
    request = _make_request("application/*")
    has_json, has_sse = transport._check_accept_headers(request)
    assert has_json, "application/* should match application/json"
    assert not has_sse, "application/* should NOT match text/event-stream"


@pytest.mark.anyio
async def test_accept_explicit_types():
    """Accept: application/json, text/event-stream should match both explicitly."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=False,
    )
    request = _make_request("application/json, text/event-stream")
    has_json, has_sse = transport._check_accept_headers(request)
    assert has_json, "application/json should match"
    assert has_sse, "text/event-stream should match"


@pytest.mark.anyio
async def test_accept_text_wildcard_alone():
    """Accept: text/* alone should match SSE but not JSON."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=False,
    )
    request = _make_request("text/*")
    has_json, has_sse = transport._check_accept_headers(request)
    assert not has_json, "text/* should NOT match application/json"
    assert has_sse, "text/* should match text/event-stream"


@pytest.mark.anyio
async def test_accept_multiple_quality_parameters():
    """Multiple types with quality parameters should all be parsed correctly."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=False,
    )
    request = _make_request("application/json;q=1.0, text/event-stream;q=0.9")
    has_json, has_sse = transport._check_accept_headers(request)
    assert has_json, "application/json;q=1.0 should match after stripping quality"
    assert has_sse, "text/event-stream;q=0.9 should match after stripping quality"
