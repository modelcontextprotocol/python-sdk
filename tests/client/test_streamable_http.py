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
from mcp_types import CONNECTION_CLOSED, METHOD_NOT_FOUND, JSONRPCError, JSONRPCNotification, JSONRPCRequest, JSONRPCResponse

from mcp.client.streamable_http import RequestContext, StreamableHTTPTransport, streamable_http_client
from mcp.shared._context_streams import create_context_streams
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
async def test_sse_response_disconnect_before_any_event_id_fails_request() -> None:
    transport = StreamableHTTPTransport("http://example.com/mcp")
    async with httpx.AsyncClient() as client:
        read_stream_writer, read_stream = create_context_streams[SessionMessage | Exception](1)
        request = JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/call", params={"name": "noop", "arguments": {}})
        ctx = RequestContext(
            client=client,
            session_id=None,
            session_message=SessionMessage(request),
            metadata=None,
            read_stream_writer=read_stream_writer,
        )
        response = httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"")

        async with read_stream_writer, read_stream:
            await transport._handle_sse_response(response, ctx)
            message = await read_stream.receive()

    assert isinstance(message, SessionMessage)
    assert isinstance(message.message, JSONRPCError)
    assert message.message.id == 1
    assert message.message.error.code == CONNECTION_CLOSED


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
async def test_initialize_post_clears_cached_pv_header_and_unstamped_posts_read_it() -> None:
    """``initialize`` discards the cached protocol-version header; every other POST reads it.

    Steps:
    1. A stamped probe POST caches its ``MCP-Protocol-Version`` header.
    2. An ``initialize`` POST clears that cache before building headers, so the fallback
       handshake never carries a probe-stamped value.
    3. A subsequent stamped POST re-seeds the cache with the negotiated version.
    4. An unstamped POST (a JSON-RPC response written by the dispatcher, which never
       passes through the session's stamp) then reads the cache and carries the
       negotiated version — the spec MUST for all post-initialization HTTP requests.
    """
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
            # An unstamped JSON-RPC response — what the dispatcher writes when answering
            # a server-initiated request (sampling/elicitation/roots).
            await write.send(SessionMessage(JSONRPCResponse(jsonrpc="2.0", id=99, result={})))

    assert [r.method for r in recorded] == ["POST", "POST", "POST", "POST"]
    assert recorded[0].headers[MCP_PROTOCOL_VERSION_HEADER] == "2026-07-28"
    assert MCP_PROTOCOL_VERSION_HEADER not in recorded[1].headers
    assert recorded[2].headers[MCP_PROTOCOL_VERSION_HEADER] == "2025-11-25"
    assert recorded[3].headers[MCP_PROTOCOL_VERSION_HEADER] == "2025-11-25"
