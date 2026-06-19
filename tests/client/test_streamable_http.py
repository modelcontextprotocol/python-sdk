"""Unit tests for the streamable-HTTP client transport.

The full client<->server round trip is pinned by the interaction suite under
tests/interaction/transports/; these tests cover the transport's per-message header
derivation directly because the headers are an HTTP-seam observation the public client
never exposes.
"""

import base64

import pytest
from inline_snapshot import snapshot

from mcp.client.streamable_http import StreamableHTTPTransport, _encode_header_value
from mcp.types import JSONRPCMessage, JSONRPCNotification, JSONRPCRequest, JSONRPCResponse


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/call", params={"name": "add", "arguments": {}}),
            snapshot({"mcp-method": "tools/call", "mcp-name": "add"}),
        ),
        (
            JSONRPCRequest(jsonrpc="2.0", id=2, method="tools/list", params={}),
            snapshot({"mcp-method": "tools/list"}),
        ),
        (
            JSONRPCNotification(jsonrpc="2.0", method="notifications/cancelled"),
            snapshot({"mcp-method": "notifications/cancelled"}),
        ),
        (
            JSONRPCResponse(jsonrpc="2.0", id=3, result={}),
            snapshot({}),
        ),
    ],
)
def test_per_message_headers_for_pinned_transport_carry_method_and_name(
    message: JSONRPCMessage, expected: dict[str, str]
) -> None:
    """A 2026-07-28-pinned transport derives ``Mcp-Method`` (and ``Mcp-Name`` for tools/call) from the body.

    ``MCP-Protocol-Version`` is not in the per-message set: ``_prepare_headers()`` adds it from the
    pin for every request, so only the method/name advisory headers vary per POST. Responses yield
    nothing because the spec only defines the headers for requests and notifications.
    """
    transport = StreamableHTTPTransport("http://test/mcp", protocol_version="2026-07-28")
    assert transport._per_message_headers(message) == expected  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("protocol_version", [None, "2025-11-25"])
def test_per_message_headers_are_empty_for_legacy_or_unpinned_transport(protocol_version: str | None) -> None:
    """An unpinned or 2025-era transport emits no per-message headers, keeping the wire byte-identical to v1."""
    transport = StreamableHTTPTransport("http://test/mcp", protocol_version=protocol_version)
    message = JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/call", params={"name": "add", "arguments": {}})
    assert transport._per_message_headers(message) == {}  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    ("raw", "expected", "wrapped"),
    [
        ("add", snapshot("add"), False),
        ("tool with spaces", snapshot("tool with spaces"), False),
        ("résumé", snapshot("=?base64?csOpc3Vtw6k=?="), True),
        ("a\r\nb", snapshot("=?base64?YQ0KYg==?="), True),
        ("=?base64?Zm9v?=", snapshot("=?base64?PT9iYXNlNjQ/Wm05dj89?="), True),
    ],
)
def test_mcp_name_header_values_are_base64_wrapped_when_unsafe_for_an_http_field(
    raw: str, expected: str, wrapped: bool
) -> None:
    """Printable-ASCII names pass verbatim; CR/LF, non-ASCII, and sentinel-shaped names are wrapped.

    The ``=?base64?...?=`` sentinel is the spec's RFC 7230 safety gate for the ``Mcp-Name`` header.
    Wrapped values round-trip through base64 so the server can recover the original name.
    """
    encoded = _encode_header_value(raw)
    assert encoded == expected
    if wrapped:
        assert encoded.startswith("=?base64?") and encoded.endswith("?=")
        assert base64.b64decode(encoded.removeprefix("=?base64?").removesuffix("?=")).decode() == raw
    else:
        assert encoded == raw


def test_constructor_pin_is_not_overwritten_by_an_initialize_result() -> None:
    """A protocol_version passed at construction wins over the InitializeResult snoop."""
    transport = StreamableHTTPTransport("http://test/mcp", protocol_version="2026-07-28")
    init = JSONRPCResponse(
        jsonrpc="2.0",
        id=1,
        result={
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "serverInfo": {"name": "s", "version": "0"},
        },
    )
    transport._maybe_extract_protocol_version_from_message(init)  # pyright: ignore[reportPrivateUsage]
    assert transport.protocol_version == "2026-07-28"
