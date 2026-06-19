"""Behaviour of the streamable-HTTP client transport under the 2026-07-28 stateless protocol.

A pinned session stamps the ``io.modelcontextprotocol/*`` `_meta` envelope onto every outgoing
request, and the streamable-HTTP transport derives the ``MCP-Protocol-Version`` / ``Mcp-Method`` /
``Mcp-Name`` headers from that body. These tests pin the transport-level derivation as pure unit
assertions on the private helpers -- the headers are an HTTP-seam observation that the public
client never exposes, and no in-process 2026 server exists yet to record them against.
"""

import base64

import pytest
from inline_snapshot import snapshot

from mcp.client.streamable_http import _body_derived_headers, _encode_header_value
from mcp.types import PROTOCOL_VERSION_META_KEY, JSONRPCMessage, JSONRPCNotification, JSONRPCRequest
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


_ENVELOPE = {PROTOCOL_VERSION_META_KEY: "2026-07-28"}


@requirement("client-transport:http:body-derived-headers")
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

    Spec-mandated for the headers themselves; tested as a unit on the private helper because the
    headers are an HTTP-seam observation -- the public client never exposes outbound request headers,
    and no in-process 2026 server exists to record them against. Legacy bodies returning ``{}`` is
    what keeps the unpinned wire byte-identical (see ``test_legacy_wire.py``).
    """
    assert _body_derived_headers(message) == expected


@requirement("client-transport:http:mcp-name-encoding")
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

    Spec-mandated: the ``=?base64?...?=`` sentinel is the spec's RFC 7230 safety gate for the
    ``Mcp-Name`` header. Unit test of the private helper for the same reason as
    :func:`_body_derived_headers` -- the encoded value is only observable on the raw HTTP request.
    Wrapped values round-trip through base64 so the server can recover the original name.
    """
    encoded = _encode_header_value(raw)
    assert encoded == expected
    if wrapped:
        assert encoded.startswith("=?base64?") and encoded.endswith("?=")
        assert base64.b64decode(encoded.removeprefix("=?base64?").removesuffix("?=")).decode() == raw
    else:
        assert encoded == raw
