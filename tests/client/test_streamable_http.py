"""Unit tests for the streamable-HTTP client transport.

The full client<->server round trip is pinned by the interaction suite under
tests/interaction/transports/; these tests cover the private header-derivation helpers
directly because the headers are an HTTP-seam observation the public client never exposes.
"""

import base64

import pytest
from inline_snapshot import snapshot

from mcp.client.streamable_http import _body_derived_headers, _encode_header_value
from mcp.types import PROTOCOL_VERSION_META_KEY, JSONRPCMessage, JSONRPCNotification, JSONRPCRequest

_ENVELOPE = {PROTOCOL_VERSION_META_KEY: "2026-07-28"}


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            JSONRPCRequest(
                jsonrpc="2.0", id=1, method="tools/call", params={"name": "add", "arguments": {}, "_meta": _ENVELOPE}
            ),
            snapshot({"mcp-protocol-version": "2026-07-28", "mcp-method": "tools/call", "mcp-name": "add"}),
        ),
        (
            JSONRPCRequest(jsonrpc="2.0", id=2, method="tools/list", params={"_meta": _ENVELOPE}),
            snapshot({"mcp-protocol-version": "2026-07-28", "mcp-method": "tools/list"}),
        ),
        (
            JSONRPCRequest(jsonrpc="2.0", id=2, method="tools/call", params={"_meta": _ENVELOPE}),
            snapshot({"mcp-protocol-version": "2026-07-28", "mcp-method": "tools/call"}),
        ),
        (
            JSONRPCRequest(jsonrpc="2.0", id=3, method="tools/call", params={"name": "add", "arguments": {}}),
            snapshot({}),
        ),
        (
            JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized"),
            snapshot({}),
        ),
    ],
)
def test_body_derived_headers_reflect_the_envelope_on_the_request_body(
    message: JSONRPCMessage, expected: dict[str, str]
) -> None:
    """An envelope-bearing body yields the three stateless headers; a legacy body yields none.

    Legacy bodies returning ``{}`` is what keeps the unpinned wire byte-identical to a pre-2026 client.
    """
    assert _body_derived_headers(message) == expected


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
