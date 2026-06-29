"""Unit tests for the streamable-HTTP client transport.

Covers header encoding and the per-message metadata-headers merge — HTTP-seam observations the
public client never exposes. The full round trip is pinned by tests/interaction/transports/.
"""

import base64
import json

import anyio
import httpx
import pytest
from inline_snapshot import snapshot
from mcp_types import METHOD_NOT_FOUND, JSONRPCError, JSONRPCNotification, JSONRPCRequest, JSONRPCResponse

from mcp.client.streamable_http import streamable_http_client
from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER, encode_header_value
from mcp.shared.message import ClientMessageMetadata, SessionMessage


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
    """The `=?base64?...?=` sentinel is the spec's RFC 7230 safety gate for `Mcp-Name`: CR/LF, non-ASCII,
    edge whitespace (forbidden in field-values; h11 rejects it), and sentinel-shaped names are wrapped so
    the server can base64-decode the original; other printable ASCII (including empty) passes verbatim."""
    encoded = encode_header_value(raw)
    assert encoded == expected
    if wrapped:
        assert encoded.startswith("=?base64?") and encoded.endswith("?=")
        assert base64.b64decode(encoded.removeprefix("=?base64?").removesuffix("?=")).decode() == raw
    else:
        assert encoded == raw


@pytest.mark.anyio
async def test_post_request_merges_per_message_metadata_headers() -> None:
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
    """Gateways and legacy servers 404 at the HTTP layer for unknown methods; with no session-id held,
    "Session terminated" is meaningless, and the discover→initialize fallback ladder keys on -32601."""

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
async def test_initialize_post_clears_cached_pv_header_and_unstamped_posts_read_it() -> None:
    """`initialize` clears the cached header so the fallback handshake never carries a probe-stamped
    value; stamped POSTs (re-)seed the cache; unstamped POSTs read it — the spec MUST for carrying
    the negotiated version on every post-initialization HTTP request."""
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        body = json.loads(request.content)
        if "id" not in body or "result" in body:
            return httpx.Response(202)
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
            await write.send(
                SessionMessage(
                    message=JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized"),
                    metadata=ClientMessageMetadata(headers={MCP_PROTOCOL_VERSION_HEADER: "2025-11-25"}),
                )
            )
            # Unstamped JSON-RPC response — what the dispatcher writes when answering a server-initiated request.
            await write.send(SessionMessage(JSONRPCResponse(jsonrpc="2.0", id=99, result={})))

    assert [r.method for r in recorded] == ["POST", "POST", "POST", "POST"]
    assert recorded[0].headers[MCP_PROTOCOL_VERSION_HEADER] == "2026-07-28"
    assert MCP_PROTOCOL_VERSION_HEADER not in recorded[1].headers
    assert recorded[2].headers[MCP_PROTOCOL_VERSION_HEADER] == "2025-11-25"
    assert recorded[3].headers[MCP_PROTOCOL_VERSION_HEADER] == "2025-11-25"
