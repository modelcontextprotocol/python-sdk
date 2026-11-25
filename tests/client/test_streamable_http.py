"""Tests for the streamable-HTTP client transport.

The full client<->server round trip is also pinned by the interaction suite under
tests/interaction/transports/. Tests here cover SSE event sizes and HTTP-seam details
that the public client never exposes.
"""

import base64
import json
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any

import anyio
import httpx2
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    CONNECTION_CLOSED,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION_META_KEY,
    CallToolRequestParams,
    CallToolResult,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from mcp_types.version import LATEST_MODERN_VERSION
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from mcp import Client, MCPError
from mcp.client.streamable_http import (
    MAX_RECONNECTION_ATTEMPTS,
    RequestContext,
    StreamableHTTPTransport,
    streamable_http_client,
)
from mcp.server import Server, ServerRequestContext
from mcp.server._streamable_http_modern import handle_modern_request
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.subscriptions import InMemorySubscriptionBus, ListenHandler, ServerEvent
from mcp.shared._context_streams import ContextSendStream, create_context_streams
from mcp.shared.dispatcher import CallOptions, DispatchContext
from mcp.shared.inbound import MCP_METHOD_HEADER, MCP_PROTOCOL_VERSION_HEADER, encode_header_value
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.message import ClientMessageMetadata, ServerMessageMetadata, SessionMessage
from mcp.shared.transport_context import TransportContext
from tests.interaction.transports import StreamingASGITransport
from tests.shared.test_dispatcher import Recorder, echo_handlers


@pytest.mark.anyio
async def test_configured_sse_limit_accepts_a_tool_result_larger_than_one_mebibyte() -> None:
    """SDK-defined: a larger SSE limit accepts a large tool result sent as one POST SSE event."""
    payload = "x" * (2 * 1024 * 1024)

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="large", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "large"
        return CallToolResult(content=[TextContent(text=payload)])

    manager = StreamableHTTPSessionManager(app=Server("large-result", on_list_tools=list_tools, on_call_tool=call_tool))
    app = Starlette(routes=[Mount("/mcp", app=manager.handle_request)])

    with anyio.fail_after(5):
        async with (
            manager.run(),
            httpx2.AsyncClient(transport=StreamingASGITransport(app)) as http,
            Client(
                streamable_http_client("http://localhost/mcp", http_client=http, max_sse_event_size=4 * 1024 * 1024),
                mode="legacy",
            ) as client,
        ):
            result = await client.call_tool("large", {})

    assert result.content == [TextContent(text=payload)]


@pytest.mark.anyio
async def test_default_sse_limit_fails_one_large_tool_call_and_keeps_the_session_usable() -> None:
    """SDK-defined: the 1 MiB default rejects one oversized tool result without poisoning the session."""
    calls: list[str] = []

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name=name, input_schema={"type": "object"}) for name in ("large", "small")])

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        calls.append(params.name)
        return CallToolResult(content=[TextContent(text="x" * (2 * 1024 * 1024) if params.name == "large" else "ok")])

    manager = StreamableHTTPSessionManager(
        app=Server("bounded-result", on_list_tools=list_tools, on_call_tool=call_tool)
    )
    app = Starlette(routes=[Mount("/mcp", app=manager.handle_request)])

    with anyio.fail_after(5):
        async with (
            manager.run(),
            httpx2.AsyncClient(transport=StreamingASGITransport(app)) as http,
            Client(streamable_http_client("http://localhost/mcp", http_client=http), mode="legacy") as client,
        ):
            with pytest.raises(MCPError) as exc_info:
                await client.call_tool("large", {})
            result = await client.call_tool("small", {})

    assert exc_info.value.error.code == CONNECTION_CLOSED
    # httpx2 owns the error detail after this prefix.
    assert exc_info.value.error.message.startswith("SSE stream failed: ")
    assert result.content == [TextContent(text="ok")]
    assert calls == ["large", "small"]


@pytest.mark.anyio
async def test_configured_sse_limit_accepts_a_large_get_notification() -> None:
    """SDK-defined: a configured limit accepts a large standalone GET event.

    The raw peer forces the notification onto GET, a transport detail hidden by the typed client.
    """
    payload = "x" * (2 * 1024 * 1024)
    notification = json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {"data": payload}})

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "GET":
            return httpx2.Response(
                200, content=f"data: {notification}\n\n".encode(), headers={"content-type": "text/event-stream"}
            )
        body = json.loads(request.content)
        if body.get("method") == "initialize":
            return httpx2.Response(
                200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}}, headers={"mcp-session-id": "s1"}
            )
        return httpx2.Response(202)

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client(
                "http://test/mcp", http_client=http, terminate_on_close=False, max_sse_event_size=4 * 1024 * 1024
            ) as (
                read,
                write,
            ),
        ):
            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=1, method="initialize", params={})))
            await read.receive()
            await write.send(SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")))
            received = await read.receive()

    assert isinstance(received, SessionMessage)
    assert isinstance(received.message, JSONRPCNotification)
    assert received.message.method == "notifications/message"
    assert received.message.params == {"data": payload}


class _ParkedSSEStream(httpx2.AsyncByteStream):
    """An SSE response body that emits one frame, then parks until closed.

    `opened` fires when the body is consumed; `closed` fires when httpx2 releases it.
    """

    def __init__(self, content: bytes = b": parked\n\n") -> None:
        self.opened = anyio.Event()
        self.closed = anyio.Event()
        self._release = anyio.Event()
        self._content = content

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.opened.set()
        yield self._content
        await self._release.wait()

    async def aclose(self) -> None:
        self.closed.set()
        self._release.set()


@pytest.mark.anyio
async def test_oversized_get_event_reconnects_and_delivers_later_messages() -> None:
    """SDK-defined: a bad GET event does not prevent later server messages or POSTs.

    The raw peer forces a bad GET followed by a fresh GET stream, which the typed client cannot schedule.
    """
    gets: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "GET":
            gets.append(request)
            if len(gets) == 1:
                content = b'retry: 0\n\ndata: {"jsonrpc":"2.0","method":"notifications/message","params":{"data":"'
                content += b"x" * 2048 + b'"}}\n\n'
                return httpx2.Response(200, content=content, headers={"content-type": "text/event-stream"})
            return httpx2.Response(
                200,
                stream=_ParkedSSEStream(
                    b'data: {"jsonrpc":"2.0","method":"notifications/message","params":{"data":"ok"}}\n\n'
                ),
                headers={"content-type": "text/event-stream"},
            )
        body = json.loads(request.content)
        if body.get("method") == "initialize":
            return httpx2.Response(
                200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}}, headers={"mcp-session-id": "s1"}
            )
        if "id" in body:
            return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        return httpx2.Response(202)

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client(
                "http://test/mcp", http_client=http, terminate_on_close=False, max_sse_event_size=1024
            ) as (read, write),
        ):
            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=1, method="initialize", params={})))
            await read.receive()
            await write.send(SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")))
            notification = await read.receive()
            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=2, method="tools/list", params={})))
            reply = await read.receive()

    assert isinstance(notification, SessionMessage)
    assert isinstance(notification.message, JSONRPCNotification)
    assert notification.message.params == {"data": "ok"}
    assert isinstance(reply, SessionMessage)
    assert isinstance(reply.message, JSONRPCResponse)
    assert reply.message.id == 2
    assert len(gets) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("limit", [0, -1])
async def test_streamable_http_rejects_nonpositive_sse_event_limits(limit: int) -> None:
    """SDK-defined: a nonpositive per-event byte limit is rejected before any HTTP request is sent."""
    with pytest.raises(ValueError) as exc_info:
        async with streamable_http_client("http://test/mcp", max_sse_event_size=limit):
            raise NotImplementedError
    assert str(exc_info.value) == snapshot("max_sse_event_size must be positive or None")


@pytest.mark.anyio
async def test_none_disables_the_sse_event_limit() -> None:
    """SDK-defined: opting out accepts a POST SSE response larger than the 1 MiB default.

    The raw peer forces SSE for the request; the typed server can choose a JSON response instead.
    """
    payload = "x" * (2 * 1024 * 1024)

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        return httpx2.Response(
            200,
            content=f'data: {{"jsonrpc":"2.0","id":{body["id"]},"result":{{"text":"{payload}"}}}}\n\n'.encode(),
            headers={"content-type": "text/event-stream"},
        )

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http, max_sse_event_size=None) as (read, write),
        ):
            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/list", params={})))
            reply = await read.receive()

    assert isinstance(reply, SessionMessage)
    assert isinstance(reply.message, JSONRPCResponse)
    assert reply.message.result == {"text": payload}


@pytest.mark.anyio
async def test_configured_sse_limit_fails_an_oversized_resumption_event() -> None:
    """SDK-defined: an oversized resumption event fails its request.

    The raw peer sends an oversized replay regardless of token state, which a typed server cannot force.
    """
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.method)
        return httpx2.Response(
            200,
            content=b'data: {"jsonrpc":"2.0","id":1,"result":{"text":"' + b"x" * 2048 + b'"}}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http, max_sse_event_size=1024) as (read, write),
        ):
            await write.send(
                SessionMessage(
                    JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/call", params={}),
                    metadata=ClientMessageMetadata(resumption_token="evt-1"),
                )
            )
            reply = await read.receive()

    assert isinstance(reply, SessionMessage)
    assert isinstance(reply.message, JSONRPCError)
    assert reply.message.error.code == CONNECTION_CLOSED
    # httpx2 owns the error detail after this prefix.
    assert reply.message.error.message.startswith("SSE stream failed: ")
    assert seen == ["GET"]


@pytest.mark.anyio
async def test_configured_sse_limit_does_not_replay_an_oversized_reconnected_event() -> None:
    """SDK-defined: a reconnect that receives an oversized event fails once; replay cannot make it smaller.

    The raw peer forces a priming event followed by an oversized replay, which a typed server cannot schedule exactly.
    """
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.method)
        if request.method == "POST":
            return httpx2.Response(
                200, content=b"id: evt-1\nretry: 0\n\n", headers={"content-type": "text/event-stream"}
            )
        assert request.headers["last-event-id"] == "evt-1"
        return httpx2.Response(
            200,
            content=b'data: {"jsonrpc":"2.0","id":1,"result":{"text":"' + b"x" * 2048 + b'"}}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http, max_sse_event_size=1024) as (read, write),
        ):
            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/call", params={})))
            reply = await read.receive()

    assert isinstance(reply, SessionMessage)
    assert isinstance(reply.message, JSONRPCError)
    assert reply.message.error.code == CONNECTION_CLOSED
    # httpx2 owns the error detail after this prefix.
    assert reply.message.error.message.startswith("SSE stream failed: ")
    assert seen == ["POST", "GET"]


@pytest.mark.anyio
async def test_non_sse_reconnection_response_retries_before_failing_the_request() -> None:
    """SDK-defined: a temporary non-SSE reconnect response does not discard the request.

    The raw peer forces a non-SSE GET followed by a valid replay, which the typed server cannot produce.
    """
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.method)
        if request.method == "POST":
            return httpx2.Response(
                200, content=b"id: evt-1\nretry: 0\n\n", headers={"content-type": "text/event-stream"}
            )
        assert request.headers["last-event-id"] == "evt-1"
        if len(seen) == 2:
            return httpx2.Response(200, content=b"temporary proxy response", headers={"content-type": "text/plain"})
        return httpx2.Response(
            200,
            content=b'data: {"jsonrpc":"2.0","id":1,"result":{}}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http, max_sse_event_size=1024) as (read, write),
        ):
            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/call", params={})))
            reply = await read.receive()

    assert isinstance(reply, SessionMessage)
    assert isinstance(reply.message, JSONRPCResponse)
    assert reply.message.id == 1
    assert seen == ["POST", "GET", "GET"]


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
    recorded: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        body = json.loads(request.content)
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
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

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404)

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
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
    recorded: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        body = json.loads(request.content)
        if "id" not in body or "result" in body:
            return httpx2.Response(202)
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
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


def _sse_or_ack_handler(
    parked: _ParkedSSEStream, posted: list[dict[str, Any]], frame_posted: anyio.Event
) -> Callable[[httpx2.Request], httpx2.Response]:
    """Requests get the parked SSE body; notifications get 202 and set `frame_posted`."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        posted.append(body)
        if "id" in body:
            return httpx2.Response(200, headers={"content-type": "text/event-stream"}, stream=parked)
        frame_posted.set()
        return httpx2.Response(202)

    return handler


@pytest.mark.anyio
async def test_modern_cancelled_frame_aborts_the_matching_in_flight_post() -> None:
    """At 2026 an outbound `notifications/cancelled` never POSTs — closing the named
    request's response stream IS the wire's cancellation signal — so the transport
    aborts the in-flight POST and swallows the frame."""
    parked = _ParkedSSEStream()
    posted: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        posted.append(json.loads(request.content))
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, stream=parked)

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http) as (_read, write),
        ):
            await write.send(
                SessionMessage(
                    message=JSONRPCRequest(jsonrpc="2.0", id="listen-1", method="subscriptions/listen", params={}),
                    metadata=ClientMessageMetadata(headers={MCP_PROTOCOL_VERSION_HEADER: LATEST_MODERN_VERSION}),
                )
            )
            await parked.opened.wait()
            await write.send(
                SessionMessage(
                    JSONRPCNotification(
                        jsonrpc="2.0", method="notifications/cancelled", params={"requestId": "listen-1"}
                    )
                )
            )
            await parked.closed.wait()
    assert [body["method"] for body in posted] == ["subscriptions/listen"]


@pytest.mark.anyio
@pytest.mark.parametrize("stamped_version", [None, "2025-11-25"], ids=["no-version-yet", "2025-11-25"])
async def test_legacy_cancelled_frame_posts_and_leaves_the_stream_open(stamped_version: str | None) -> None:
    """Below 2026 — or before any stamped POST has revealed the version — the frame is
    the spec's cancellation signal: it POSTs, and the request's stream stays open
    (a 2025 disconnect is explicitly not a cancel)."""
    parked = _ParkedSSEStream()
    posted: list[dict[str, Any]] = []
    frame_posted = anyio.Event()
    handler = _sse_or_ack_handler(parked, posted, frame_posted)

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http) as (_read, write),
        ):
            metadata = (
                ClientMessageMetadata(headers={MCP_PROTOCOL_VERSION_HEADER: stamped_version})
                if stamped_version is not None
                else None
            )
            await write.send(
                SessionMessage(
                    message=JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/call", params={}),
                    metadata=metadata,
                )
            )
            await parked.opened.wait()
            await write.send(
                SessionMessage(
                    JSONRPCNotification(jsonrpc="2.0", method="notifications/cancelled", params={"requestId": 1})
                )
            )
            await frame_posted.wait()
            # Checked before teardown: exiting the transport cancels the parked POST.
            assert not parked.closed.is_set()
    assert [body["method"] for body in posted] == ["tools/call", "notifications/cancelled"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"requestId": 999}, id="unknown-id"),
        pytest.param({"requestId": True}, id="bool-must-not-alias-request-id-1"),
        pytest.param({"requestId": "1"}, id="string-1-must-not-match-int-1"),
        pytest.param({}, id="no-request-id"),
        pytest.param(None, id="no-params"),
    ],
)
async def test_modern_cancelled_frames_matching_no_post_are_swallowed(params: dict[str, Any] | None) -> None:
    """At 2026 the frame is swallowed even when it aborts nothing — the wire defines no
    client-to-server notifications, so a late cancel racing the response must not leak
    a POST — and a mismatched id must not abort someone else's stream."""
    parked = _ParkedSSEStream()
    posted: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        posted.append(body)
        if body.get("id") == 1:
            return httpx2.Response(200, headers={"content-type": "text/event-stream"}, stream=parked)
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http) as (read, write),
        ):
            await write.send(
                SessionMessage(
                    message=JSONRPCRequest(jsonrpc="2.0", id=1, method="subscriptions/listen", params={}),
                    metadata=ClientMessageMetadata(headers={MCP_PROTOCOL_VERSION_HEADER: LATEST_MODERN_VERSION}),
                )
            )
            await parked.opened.wait()
            await write.send(
                SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/cancelled", params=params))
            )
            # A follow-up request completing proves the loop moved past the swallowed frame.
            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=2, method="ping", params={})))
            reply = await read.receive()
            # Checked before teardown: exiting the transport cancels the parked POST.
            assert not parked.closed.is_set()
    assert isinstance(reply, SessionMessage)
    assert isinstance(reply.message, JSONRPCResponse)
    assert reply.message.id == 2
    assert [body["method"] for body in posted] == ["subscriptions/listen", "ping"]


@pytest.mark.anyio
async def test_handler_scoped_cancelled_frames_are_translated_at_modern_too() -> None:
    """A cancel carrying `ServerMessageMetadata` (a handler abandoning its own
    back-channel request) still names one of OUR outbound ids — every spec-legal
    cancel names a request its sender issued — so at 2026 it aborts that POST and
    stays off the wire like any other."""
    parked = _ParkedSSEStream()
    posted: list[dict[str, Any]] = []
    frame_posted = anyio.Event()
    handler = _sse_or_ack_handler(parked, posted, frame_posted)

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http) as (_read, write),
        ):
            await write.send(
                SessionMessage(
                    message=JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/call", params={}),
                    metadata=ClientMessageMetadata(headers={MCP_PROTOCOL_VERSION_HEADER: LATEST_MODERN_VERSION}),
                )
            )
            await parked.opened.wait()
            await write.send(
                SessionMessage(
                    message=JSONRPCNotification(
                        jsonrpc="2.0", method="notifications/cancelled", params={"requestId": 1}
                    ),
                    metadata=ServerMessageMetadata(related_request_id=99),
                )
            )
            await parked.closed.wait()
    assert [body["method"] for body in posted] == ["tools/call"]
    assert not frame_posted.is_set()


@pytest.mark.anyio
async def test_cancel_for_a_request_sent_under_2025_still_posts_after_modern_adoption() -> None:
    """The translation follows the era the NAMED request was sent under, not the
    cache at cancel time: a request POSTed under 2025 keeps 2025 cancellation
    semantics (frame on the wire, stream left open) even after a later message
    flips the negotiated version to 2026."""
    parked = _ParkedSSEStream()
    posted: list[dict[str, Any]] = []
    frame_posted = anyio.Event()

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        posted.append(body)
        if body.get("id") == 1:
            return httpx2.Response(200, headers={"content-type": "text/event-stream"}, stream=parked)
        if "id" in body:
            return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        frame_posted.set()
        return httpx2.Response(202)

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http) as (read, write),
        ):
            await write.send(
                SessionMessage(
                    message=JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/call", params={}),
                    metadata=ClientMessageMetadata(headers={MCP_PROTOCOL_VERSION_HEADER: "2025-11-25"}),
                )
            )
            await parked.opened.wait()
            # A modern-stamped request flips the cached negotiated version.
            await write.send(
                SessionMessage(
                    message=JSONRPCRequest(jsonrpc="2.0", id=2, method="ping", params={}),
                    metadata=ClientMessageMetadata(headers={MCP_PROTOCOL_VERSION_HEADER: LATEST_MODERN_VERSION}),
                )
            )
            reply = await read.receive()
            assert isinstance(reply, SessionMessage)
            assert isinstance(reply.message, JSONRPCResponse)
            await write.send(
                SessionMessage(
                    JSONRPCNotification(jsonrpc="2.0", method="notifications/cancelled", params={"requestId": 1})
                )
            )
            await frame_posted.wait()
            # Checked before teardown: exiting the transport cancels the parked POST.
            assert not parked.closed.is_set()
    assert [body["method"] for body in posted] == ["tools/call", "ping", "notifications/cancelled"]


class _SignalingBus(InMemorySubscriptionBus):
    """Signals subscribe/unsubscribe so a test observes the stream lifecycle through
    the bus Protocol (the public seam) instead of polling handler internals."""

    def __init__(self) -> None:
        super().__init__()
        self.subscribed = anyio.Event()
        self.unsubscribed = anyio.Event()

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        unsubscribe = super().subscribe(listener)
        self.subscribed.set()

        def unsubscribe_and_signal() -> None:
            unsubscribe()
            self.unsubscribed.set()

        return unsubscribe_and_signal


@pytest.mark.anyio
async def test_scope_cancel_aborts_a_modern_listen_post_end_to_end() -> None:
    """Over a real ASGI bridge: cancelling the caller of a parked `subscriptions/listen`
    closes the POST's response stream — the server treats the disconnect as the cancel
    and releases the subscription — and no `notifications/cancelled` crosses the wire."""
    bus = _SignalingBus()
    server = Server("test", on_subscriptions_listen=ListenHandler(bus))

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        async with server.lifespan(server) as lifespan_state:
            await handle_modern_request(server, None, False, lifespan_state, scope, receive, send)

    posted_methods: list[str] = []

    async def record_request(request: httpx2.Request) -> None:
        posted_methods.append(json.loads(request.content)["method"])

    acked = anyio.Event()

    async def on_notify(dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None) -> None:
        assert method == "notifications/subscriptions/acknowledged"
        acked.set()

    on_request, _ = echo_handlers(Recorder())

    with anyio.fail_after(15):
        async with (
            httpx2.AsyncClient(
                transport=StreamingASGITransport(app),
                base_url="http://testserver",
                event_hooks={"request": [record_request]},
            ) as http,
            streamable_http_client("http://testserver/mcp", http_client=http) as (read, write),
        ):
            dispatcher: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(read, write)
            async with anyio.create_task_group() as tg:  # pragma: no branch
                await tg.start(dispatcher.run, on_request, on_notify)
                listen_scope = anyio.CancelScope()

                async def send_listen() -> None:
                    params: dict[str, Any] = {
                        "_meta": {
                            PROTOCOL_VERSION_META_KEY: LATEST_MODERN_VERSION,
                            CLIENT_INFO_META_KEY: {"name": "test-client", "version": "0"},
                            CLIENT_CAPABILITIES_META_KEY: {},
                        },
                        "notifications": {"toolsListChanged": True},
                    }
                    opts: CallOptions = {
                        "request_id": "listen-1",
                        "headers": {
                            MCP_PROTOCOL_VERSION_HEADER: LATEST_MODERN_VERSION,
                            MCP_METHOD_HEADER: "subscriptions/listen",
                        },
                    }
                    with listen_scope:
                        await dispatcher.send_raw_request("subscriptions/listen", params, opts)

                tg.start_soon(send_listen)
                await acked.wait()
                assert bus.subscribed.is_set()
                assert not bus.unsubscribed.is_set()
                listen_scope.cancel()
                await bus.unsubscribed.wait()
                tg.cancel_scope.cancel()
    assert posted_methods == ["subscriptions/listen"]


class _CompletingSSEStream(httpx2.AsyncByteStream):
    """An SSE body that delivers one JSON-RPC response, then parks in `aclose`.

    Holding `aclose` keeps the finished POST task alive past its response, so a
    test can re-register the same request id underneath it before releasing.
    """

    def __init__(self, response_body: dict[str, Any]) -> None:
        self._event = f"data: {json.dumps(response_body)}\n\n".encode()
        self.release = anyio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._event

    async def aclose(self) -> None:
        await self.release.wait()


@pytest.mark.anyio
async def test_a_finished_post_task_does_not_evict_a_reused_ids_new_registration() -> None:
    """Request ids are reusable once resolved; a finished POST task unwinding late
    must not pop the successor's registration, or a cancel for the reused id would
    find nothing to abort and the live POST would leak past the cancellation."""
    completing = _CompletingSSEStream({"jsonrpc": "2.0", "id": "dup-1", "result": {}})
    parked = _ParkedSSEStream()
    posted: list[dict[str, Any]] = []
    streams = [completing, parked]

    def handler(request: httpx2.Request) -> httpx2.Response:
        posted.append(json.loads(request.content))
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, stream=streams.pop(0))

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http) as (read, write),
        ):
            modern = ClientMessageMetadata(headers={MCP_PROTOCOL_VERSION_HEADER: LATEST_MODERN_VERSION})
            await write.send(
                SessionMessage(
                    message=JSONRPCRequest(jsonrpc="2.0", id="dup-1", method="tools/call", params={}),
                    metadata=modern,
                )
            )
            reply = await read.receive()
            assert isinstance(reply, SessionMessage)
            assert isinstance(reply.message, JSONRPCResponse)
            # The first task is now parked in `aclose`; reuse its id underneath it.
            await write.send(
                SessionMessage(
                    message=JSONRPCRequest(jsonrpc="2.0", id="dup-1", method="subscriptions/listen", params={}),
                    metadata=modern,
                )
            )
            await parked.opened.wait()
            completing.release.set()
            await anyio.wait_all_tasks_blocked()
            # The successor's registration survived: a cancel still aborts it.
            await write.send(
                SessionMessage(
                    JSONRPCNotification(jsonrpc="2.0", method="notifications/cancelled", params={"requestId": "dup-1"})
                )
            )
            await parked.closed.wait()
    assert [body["method"] for body in posted] == ["tools/call", "subscriptions/listen"]


class _DyingSSEStream(httpx2.AsyncByteStream):
    """Emits one id-less comment then breaks - a non-resumable stream dropping."""

    def __init__(self) -> None:
        self.opened = anyio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.opened.set()
        yield b": hello\n\n"
        raise httpx2.ReadError("connection reset")

    async def aclose(self) -> None:
        pass


@pytest.mark.anyio
async def test_a_non_resumable_sse_drop_resolves_the_request_with_an_error() -> None:
    """A per-request SSE stream that dies having carried no event ids can never deliver its
    response; the transport resolves the waiter with CONNECTION_CLOSED instead of hanging forever."""
    dying = _DyingSSEStream()

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, stream=dying)

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http) as (read, write),
        ):
            await write.send(
                SessionMessage(JSONRPCRequest(jsonrpc="2.0", id="listen-1", method="subscriptions/listen", params={}))
            )
            reply = await read.receive()
    assert isinstance(reply, SessionMessage)
    assert isinstance(reply.message, JSONRPCError)
    assert reply.message.id == "listen-1"
    assert reply.message.error.code == CONNECTION_CLOSED


class _DeliverOnCommandSSEStream(httpx2.AsyncByteStream):
    """Parks after opening, then delivers one JSON-RPC response when told."""

    def __init__(self, response_body: dict[str, Any]) -> None:
        self._event = f"data: {json.dumps(response_body)}\n\n".encode()
        self.opened = anyio.Event()
        self.deliver = anyio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.opened.set()
        await self.deliver.wait()
        yield self._event

    async def aclose(self) -> None:
        pass


@pytest.mark.anyio
async def test_a_superseded_posts_late_real_response_cannot_answer_the_successor() -> None:
    """SDK-defined: re-issuing an id severs the superseded POST, so nothing from its
    stream (a late real response, or a synthesized error for its death) can resolve
    the reused id's waiter; only the successor's own response arrives."""
    stale = _DeliverOnCommandSSEStream({"jsonrpc": "2.0", "id": "dup-1", "result": {"origin": "stale"}})
    succeeding = _DeliverOnCommandSSEStream({"jsonrpc": "2.0", "id": "dup-1", "result": {"origin": "fresh"}})
    streams: list[httpx2.AsyncByteStream] = [stale, succeeding]

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, stream=streams.pop(0))

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http) as (read, write),
        ):
            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id="dup-1", method="tools/call", params={})))
            await stale.opened.wait()
            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id="dup-1", method="tools/call", params={})))
            await succeeding.opened.wait()
            stale.deliver.set()
            await anyio.wait_all_tasks_blocked()
            succeeding.deliver.set()
            reply = await read.receive()
    assert isinstance(reply, SessionMessage)
    assert isinstance(reply.message, JSONRPCResponse), reply.message
    assert reply.message.result == {"origin": "fresh"}


@pytest.mark.anyio
async def test_a_202_to_a_request_resolves_the_waiter_with_an_error() -> None:
    """SDK-defined: a server that answers a request with 202 Accepted has declared no
    response will follow (the spec requires SSE or JSON for requests); the transport
    resolves the waiter with INVALID_REQUEST instead of parking the caller forever."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(202)

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http) as (read, write),
        ):
            await write.send(
                SessionMessage(JSONRPCRequest(jsonrpc="2.0", id="listen-1", method="subscriptions/listen", params={}))
            )
            reply = await read.receive()
    assert isinstance(reply, SessionMessage)
    assert isinstance(reply.message, JSONRPCError)
    assert reply.message.id == "listen-1"
    assert reply.message.error.code == INVALID_REQUEST


def _abandoned_request_context(
    http: httpx2.AsyncClient, send: ContextSendStream[SessionMessage | Exception]
) -> RequestContext:
    return RequestContext(
        client=http,
        session_id=None,
        session_message=SessionMessage(
            JSONRPCRequest(jsonrpc="2.0", id="listen-1", method="subscriptions/listen", params={})
        ),
        metadata=None,
        read_stream_writer=send,
    )


@pytest.mark.anyio
async def test_exhausted_reconnection_attempts_resolve_the_request_with_an_error() -> None:
    """An id-bearing stream that exhausts its reconnection budget also resolves the waiter with CONNECTION_CLOSED."""
    transport = StreamableHTTPTransport("http://test/mcp")
    send, receive = create_context_streams[SessionMessage | Exception](1)
    async with httpx2.AsyncClient() as http:
        with anyio.fail_after(5):
            await transport._handle_reconnection(  # pyright: ignore[reportPrivateUsage]
                _abandoned_request_context(http, send), "evt-7", None, MAX_RECONNECTION_ATTEMPTS
            )
            reply = await receive.receive()
    assert isinstance(reply, SessionMessage)
    assert isinstance(reply.message, JSONRPCError)
    assert reply.message.id == "listen-1"
    assert reply.message.error.code == CONNECTION_CLOSED
    send.close()
    receive.close()


@pytest.mark.anyio
async def test_resolving_an_abandoned_request_after_the_reader_closed_is_contained() -> None:
    """Teardown race: a stream dying after the reader closed resolves best-effort and must not crash."""
    transport = StreamableHTTPTransport("http://test/mcp")
    send, receive = create_context_streams[SessionMessage | Exception](1)
    receive.close()
    async with httpx2.AsyncClient() as http:
        with anyio.fail_after(5):
            await transport._handle_reconnection(  # pyright: ignore[reportPrivateUsage]
                _abandoned_request_context(http, send), "evt-7", None, MAX_RECONNECTION_ATTEMPTS
            )
    send.close()


@pytest.mark.anyio
async def test_trailing_slash_redirect_within_origin_is_followed_by_the_transport() -> None:
    """SDK-defined: a redirect that stays on the endpoint's origin (here Starlette's Mount sending
    /mcp to /mcp/) is followed by the transport itself, so a caller-supplied client left at
    httpx2's no-follow default still connects."""
    session_manager = StreamableHTTPSessionManager(app=Server("redirect-test"))
    app = Starlette(routes=[Mount("/mcp", app=session_manager.handle_request)])
    urls: list[str] = []

    async def record(request: httpx2.Request) -> None:
        urls.append(str(request.url))

    with anyio.fail_after(5):
        async with (
            session_manager.run(),
            httpx2.AsyncClient(transport=StreamingASGITransport(app), event_hooks={"request": [record]}) as http,
            Client(streamable_http_client("http://mcp.example/mcp", http_client=http)) as client,
        ):
            assert client.server_info is not None
            assert client.server_info.name == "redirect-test"

    assert urls[:2] == ["http://mcp.example/mcp", "http://mcp.example/mcp/"]


class _RedirectPromptsListElsewhere(httpx2.AsyncBaseTransport):
    """Serves `app` in process, except that a prompts/list POST is answered with a redirect to
    another origin."""

    def __init__(self, app: Starlette) -> None:
        self.inner = StreamingASGITransport(app)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        if request.method == "POST" and json.loads(request.content).get("method") == "prompts/list":
            return httpx2.Response(307, headers={"location": "http://other.example/mcp/"})
        return await self.inner.handle_async_request(request)

    async def __aenter__(self) -> "_RedirectPromptsListElsewhere":
        await self.inner.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.inner.__aexit__(*args)


@pytest.mark.anyio
async def test_redirect_to_another_origin_fails_that_call_and_keeps_the_session() -> None:
    """SDK-defined: a redirect pointing outside the endpoint's origin is not followed, whatever the
    caller's client is configured to do: the call it answered fails with MCPError naming the
    location, nothing is sent to the other origin, and the session stays usable."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[])

    session_manager = StreamableHTTPSessionManager(app=Server("redirect-test", on_list_tools=list_tools))
    app = Starlette(routes=[Mount("/mcp", app=session_manager.handle_request)])
    urls: list[str] = []

    async def record(request: httpx2.Request) -> None:
        urls.append(str(request.url))

    with anyio.fail_after(5):
        async with (
            session_manager.run(),
            httpx2.AsyncClient(
                transport=_RedirectPromptsListElsewhere(app), event_hooks={"request": [record]}, follow_redirects=True
            ) as http,
            Client(streamable_http_client("http://mcp.example/mcp/", http_client=http)) as client,
        ):
            with pytest.raises(MCPError) as exc_info:
                await client.list_prompts()
            assert (await client.list_tools()).tools == []

    assert exc_info.value.error.code == INVALID_REQUEST
    assert exc_info.value.error.message == snapshot(
        "Redirect to http://other.example/mcp/ not followed; use that URL as the endpoint if it is the intended server"
    )
    assert [url for url in urls if "other.example" in url] == []


@pytest.mark.anyio
async def test_redirected_notification_is_dropped_and_the_next_message_still_goes_out() -> None:
    """SDK-defined: a notification whose POST is redirected outside the origin has no waiter to
    resolve, so it is logged and dropped; the transport keeps serving the write stream."""
    urls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        urls.append(str(request.url))
        return httpx2.Response(307, headers={"location": "http://other.example/mcp"})

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http) as (read, write),
        ):
            await write.send(
                SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/roots/list_changed"))
            )
            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=7, method="tools/list", params={})))
            reply = await read.receive()
    assert isinstance(reply, SessionMessage)
    assert isinstance(reply.message, JSONRPCError)
    assert reply.message.id == 7
    assert reply.message.error.code == INVALID_REQUEST
    assert urls == ["http://test/mcp", "http://test/mcp"]


@pytest.mark.anyio
async def test_get_stream_gives_up_without_retrying_when_the_endpoint_redirects_elsewhere() -> None:
    """SDK-defined: the standalone GET stream is not opened through a redirect to another origin,
    and since the same GET would be redirected again the transport logs it and stops instead of
    spending its reconnection attempts."""
    gets: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        gets.append(str(request.url))
        return httpx2.Response(307, headers={"location": "http://other.example/mcp"})

    transport = StreamableHTTPTransport("http://test/mcp")
    transport.session_id = "session-1"
    send, receive = create_context_streams[SessionMessage | Exception](1)
    with anyio.fail_after(5):
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
            await transport.handle_get_stream(http, send)
    assert gets == ["http://test/mcp"]
    send.close()
    receive.close()


@pytest.mark.anyio
async def test_resumption_redirected_elsewhere_resolves_that_request_with_an_error() -> None:
    """SDK-defined: a resumption GET answered with a redirect to another origin is not followed;
    the resumed request is resolved with an error naming the location rather than left waiting."""
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append((f"{request.method} {request.url}", request.headers.get("last-event-id")))
        return httpx2.Response(307, headers={"location": "http://other.example/mcp"})

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client("http://test/mcp", http_client=http) as (read, write),
        ):
            await write.send(
                SessionMessage(
                    JSONRPCRequest(jsonrpc="2.0", id="resume-1", method="tools/call", params={}),
                    metadata=ClientMessageMetadata(resumption_token="evt-41"),
                )
            )
            reply = await read.receive()
    assert isinstance(reply, SessionMessage)
    assert isinstance(reply.message, JSONRPCError)
    assert reply.message.id == "resume-1"
    assert reply.message.error.code == INVALID_REQUEST
    assert reply.message.error.message == snapshot(
        "Redirect to http://other.example/mcp not followed; use that URL as the endpoint if it is the intended server"
    )
    assert seen == [("GET http://test/mcp", "evt-41")]


async def _redirected_call_error(url: str, location: str) -> str:
    """Send one request through streamable_http_client to a server answering `url` with a 307 to
    `location`, and return the message of the error that resolves it."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(307, headers={"location": location})

    with anyio.fail_after(5):
        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http,
            streamable_http_client(url, http_client=http) as (read, write),
        ):
            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/list", params={})))
            reply = await read.receive()
    assert isinstance(reply, SessionMessage)
    assert isinstance(reply.message, JSONRPCError)
    return reply.message.error.message


@pytest.mark.anyio
async def test_https_endpoint_redirected_to_plain_http_is_explained_and_the_https_form_suggested() -> None:
    """SDK-authored text: a redirect of an HTTPS endpoint to plain HTTP on the same host (the usual
    sign of a TLS-terminating proxy the server does not trust) never suggests the http:// URL."""
    message = await _redirected_call_error("https://mcp.example/mcp", "http://mcp.example/mcp/")
    assert message == snapshot("""\
Redirect to http://mcp.example/mcp/ not followed: it would downgrade this HTTPS endpoint to plain HTTP.
The server is likely behind a TLS-terminating proxy whose forwarded headers it does not trust,
often combined with a trailing-slash difference. Try https://mcp.example/mcp/ instead, or fix the proxy settings.\
""")


@pytest.mark.anyio
async def test_unfollowed_redirect_location_is_named_without_its_query_string() -> None:
    """SDK-authored text: the location is reported without query or userinfo, which may carry state
    that does not belong in an error message or a log line."""
    message = await _redirected_call_error("http://mcp.example/mcp", "https://sso.example/login?state=s3cr3t&nonce=n")
    assert message == snapshot(
        "Redirect to https://sso.example/login not followed; use that URL as the endpoint if it is the intended server"
    )


@pytest.mark.anyio
async def test_https_endpoint_redirected_to_plain_http_elsewhere_never_suggests_the_http_url() -> None:
    """SDK-authored text: the downgrade explanation applies whatever host the http:// location names,
    so the message never offers a plain-HTTP URL as the endpoint to configure."""
    message = await _redirected_call_error("https://mcp.example/mcp", "http://backend.lan:8000/mcp/")
    assert message == snapshot("""\
Redirect to http://backend.lan:8000/mcp/ not followed: it would downgrade this HTTPS endpoint to plain HTTP.
The server is likely behind a TLS-terminating proxy whose forwarded headers it does not trust,
often combined with a trailing-slash difference. Try https://backend.lan:8000/mcp/ instead, or fix the proxy settings.\
""")
