"""Unit tests for the streamable-HTTP client transport.

The full client<->server round trip is pinned by the interaction suite under
tests/interaction/transports/; these tests cover the transport's header encoding and the
per-message metadata-headers merge directly because the headers are an HTTP-seam observation
the public client never exposes.
"""

import base64
import json

import anyio
import httpx
import pytest
from inline_snapshot import snapshot

from mcp.client.streamable_http import streamable_http_client
from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER, encode_header_value
from mcp.shared.message import ClientMessageMetadata, SessionMessage
from mcp.types import METHOD_NOT_FOUND, JSONRPCError, JSONRPCRequest


@pytest.mark.parametrize(
    ("raw", "expected", "wrapped"),
    [
        ("add", snapshot("add"), False),
        ("", snapshot(""), False),
        ("tool with spaces", snapshot("tool with spaces"), False),
        (" add", snapshot("=?base64?IGFkZA==?="), True),
        ("add ", snapshot("=?base64?YWRkIA==?="), True),
        ("résumé", snapshot("=?base64?csOpc3Vtw6k=?="), True),
        ("a\r\nb", snapshot("=?base64?YQ0KYg==?="), True),
        ("=?base64?Zm9v?=", snapshot("=?base64?PT9iYXNlNjQ/Wm05dj89?="), True),
    ],
)
def test_mcp_name_header_values_are_base64_wrapped_when_unsafe_for_an_http_field(
    raw: str, expected: str, wrapped: bool
) -> None:
    """Printable-ASCII names pass verbatim; CR/LF, non-ASCII, edge-whitespace, and sentinel-shaped names are wrapped.

    The ``=?base64?...?=`` sentinel is the spec's RFC 7230 safety gate for the ``Mcp-Name`` header.
    Wrapped values round-trip through base64 so the server can recover the original name. A leading
    or trailing space is wrapped because RFC 7230 forbids it in field-values (h11 rejects on real
    transports); an empty value is allowed and passes verbatim.
    """
    encoded = encode_header_value(raw)
    assert encoded == expected
    if wrapped:
        assert encoded.startswith("=?base64?") and encoded.endswith("?=")
        assert base64.b64decode(encoded.removeprefix("=?base64?").removesuffix("?=")).decode() == raw
    else:
        assert encoded == raw


@pytest.mark.anyio
async def test_post_request_merges_per_message_metadata_headers() -> None:
    """`ClientMessageMetadata.headers` on a `SessionMessage` are merged into the outgoing POST headers
    (SDK-defined: the headers sidecar is the path the session uses to reach the transport)."""
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})

    with anyio.fail_after(5):
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http) as (read, write),
        ):
            await write.send(
                SessionMessage(
                    message=JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/list", params={}),
                    metadata=ClientMessageMetadata(headers={"x-test": "v"}),
                )
            )
            reply = await read.receive()
    assert isinstance(reply, SessionMessage)
    assert [r.method for r in recorded] == ["POST"]
    assert recorded[0].headers["x-test"] == "v"


@pytest.mark.anyio
async def test_pre_session_bare_404_maps_to_method_not_found() -> None:
    """A bare HTTP 404 (no JSON-RPC body) before any session-id is held maps to METHOD_NOT_FOUND.

    Gateways and legacy servers 404 at the HTTP layer for unknown methods; with no session yet,
    "Session terminated" is meaningless, and the discover→initialize fallback ladder keys on -32601.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with anyio.fail_after(5):
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http) as (read, write),
        ):
            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=1, method="server/discover", params={})))
            reply = await read.receive()
    assert isinstance(reply, SessionMessage)
    assert isinstance(reply.message, JSONRPCError)
    assert reply.message.error.code == METHOD_NOT_FOUND


@pytest.mark.anyio
async def test_post_does_not_read_cached_protocol_version_header() -> None:
    """A POST's protocol-version header comes only from its own ``metadata.headers``.

    The first POST carries (and caches) a pv header; the second POST sends no metadata
    and must therefore carry no pv header — a stale cached value would poison the
    fallback ``initialize`` after a failed discover probe. The cache exists for
    transport-internal GET/DELETE only.
    """
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})

    with anyio.fail_after(5):
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http) as (read, write),
        ):
            await write.send(
                SessionMessage(
                    message=JSONRPCRequest(jsonrpc="2.0", id=1, method="server/discover", params={}),
                    metadata=ClientMessageMetadata(headers={MCP_PROTOCOL_VERSION_HEADER: "2026-07-28"}),
                )
            )
            await read.receive()
            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=2, method="initialize", params={})))
            await read.receive()
    assert [r.method for r in recorded] == ["POST", "POST"]
    assert recorded[0].headers[MCP_PROTOCOL_VERSION_HEADER] == "2026-07-28"
    assert MCP_PROTOCOL_VERSION_HEADER not in recorded[1].headers
