"""Unit tests for the streamable-HTTP client transport.

The full client<->server round trip is pinned by the interaction suite under
tests/interaction/transports/; these tests cover the transport's header encoding and the
per-message metadata-headers merge directly because the headers are an HTTP-seam observation
the public client never exposes.
"""

import base64
import json
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any

import anyio
import httpx
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    CONNECTION_CLOSED,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION_META_KEY,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)
from mcp_types.version import LATEST_MODERN_VERSION
from starlette.types import Receive, Scope, Send

from mcp.client.streamable_http import (
    MAX_RECONNECTION_ATTEMPTS,
    RequestContext,
    StreamableHTTPTransport,
    streamable_http_client,
)
from mcp.server import Server
from mcp.server._streamable_http_modern import handle_modern_request
from mcp.server.subscriptions import InMemorySubscriptionBus, ListenHandler, ServerEvent
from mcp.shared._context_streams import ContextSendStream, create_context_streams
from mcp.shared.dispatcher import CallOptions, DispatchContext
from mcp.shared.inbound import MCP_METHOD_HEADER, MCP_PROTOCOL_VERSION_HEADER, encode_header_value
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.message import ClientMessageMetadata, ServerMessageMetadata, SessionMessage
from mcp.shared.transport_context import TransportContext
from tests.interaction.transports import StreamingASGITransport
from tests.shared.test_dispatcher import Recorder, echo_handlers


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


class _ParkedSSEStream(httpx.AsyncByteStream):
    """An SSE response body that emits one comment line, then parks until closed.

    `opened` fires once the transport is iterating the body (the POST is truly in
    flight); `closed` fires when httpx tears the body down — the observable proof
    that an abort, not a response, ended the stream.
    """

    def __init__(self) -> None:
        self.opened = anyio.Event()
        self.closed = anyio.Event()
        self._release = anyio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.opened.set()
        yield b": parked\n\n"
        await self._release.wait()

    async def aclose(self) -> None:
        self.closed.set()
        self._release.set()


def _sse_or_ack_handler(
    parked: _ParkedSSEStream, posted: list[dict[str, Any]], frame_posted: anyio.Event
) -> Callable[[httpx.Request], httpx.Response]:
    """Requests get the parked SSE body; notifications get 202 and set `frame_posted`."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        posted.append(body)
        if "id" in body:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=parked)
        frame_posted.set()
        return httpx.Response(202)

    return handler


@pytest.mark.anyio
async def test_modern_cancelled_frame_aborts_the_matching_in_flight_post() -> None:
    """At 2026 an outbound `notifications/cancelled` never POSTs — closing the named
    request's response stream IS the wire's cancellation signal — so the transport
    aborts the in-flight POST and swallows the frame."""
    parked = _ParkedSSEStream()
    posted: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=parked)

    with anyio.fail_after(5):
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
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
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
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

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        posted.append(body)
        if body.get("id") == 1:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=parked)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})

    with anyio.fail_after(5):
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
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
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
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

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        posted.append(body)
        if body.get("id") == 1:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=parked)
        if "id" in body:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        frame_posted.set()
        return httpx.Response(202)

    with anyio.fail_after(5):
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
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

    async def record_request(request: httpx.Request) -> None:
        posted_methods.append(json.loads(request.content)["method"])

    acked = anyio.Event()

    async def on_notify(dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None) -> None:
        assert method == "notifications/subscriptions/acknowledged"
        acked.set()

    on_request, _ = echo_handlers(Recorder())

    with anyio.fail_after(15):
        async with (
            httpx.AsyncClient(
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


class _CompletingSSEStream(httpx.AsyncByteStream):
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

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=streams.pop(0))

    with anyio.fail_after(5):
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
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


class _DyingSSEStream(httpx.AsyncByteStream):
    """Emits one id-less comment then breaks - a non-resumable stream dropping."""

    def __init__(self) -> None:
        self.opened = anyio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.opened.set()
        yield b": hello\n\n"
        raise httpx.ReadError("connection reset")

    async def aclose(self) -> None:
        pass


@pytest.mark.anyio
async def test_a_non_resumable_sse_drop_resolves_the_request_with_an_error() -> None:
    """A per-request SSE stream that dies having carried no event ids can never
    deliver its response; the transport resolves the waiter with CONNECTION_CLOSED
    instead of leaving the request pending for the session's lifetime (a listen
    stream's consumer would otherwise hang instead of learning it is lost)."""
    dying = _DyingSSEStream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=dying)

    with anyio.fail_after(5):
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
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


def _abandoned_request_context(
    http: httpx.AsyncClient, send: ContextSendStream[SessionMessage | Exception]
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
    """The sibling of the non-resumable drop: an id-bearing stream whose
    reconnection budget runs out also resolves the waiter - the no-silent-hang
    guarantee is unconditional, not conditional on the server never stamping
    event ids."""
    transport = StreamableHTTPTransport("http://test/mcp")
    send, receive = create_context_streams[SessionMessage | Exception](1)
    async with httpx.AsyncClient() as http:
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
    """Teardown race: the session can close the read stream's receive end while
    a request's SSE stream is still dying; the resolution write is best-effort
    (nobody is waiting) and must not crash the transport task group."""
    transport = StreamableHTTPTransport("http://test/mcp")
    send, receive = create_context_streams[SessionMessage | Exception](1)
    receive.close()
    async with httpx.AsyncClient() as http:
        with anyio.fail_after(5):
            await transport._handle_reconnection(  # pyright: ignore[reportPrivateUsage]
                _abandoned_request_context(http, send), "evt-7", None, MAX_RECONNECTION_ATTEMPTS
            )
    send.close()
