"""Regression coverage for the StreamableHTTP per-session response router."""

import gc

import anyio
import httpx2
import pytest
from mcp_types import JSONRPCMessage, JSONRPCNotification, JSONRPCRequest, JSONRPCResponse, jsonrpc_message_adapter
from starlette.types import Message, Scope

from mcp.server.streamable_http import (
    REQUEST_STREAM_BUFFER_SIZE,
    EventCallback,
    EventId,
    EventMessage,
    EventStore,
    StreamableHTTPServerTransport,
    StreamId,
)
from mcp.shared.message import SessionMessage


class _PrimingFailingStore(EventStore):
    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        raise RuntimeError("backend unavailable")

    async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
        raise NotImplementedError


class _AsgiPost:
    """A one-shot POST driven straight at `handle_request`, capturing what the transport sends."""

    def __init__(self, body: bytes, headers: list[tuple[bytes, bytes]]) -> None:
        self.scope: Scope = {"type": "http", "method": "POST", "path": "/", "query_string": b"", "headers": headers}
        self.sent: list[Message] = []
        self._body = body
        self._body_sent = False

    async def receive(self) -> Message:
        if not self._body_sent:
            self._body_sent = True
            return {"type": "http.request", "body": self._body, "more_body": False}
        raise NotImplementedError

    async def send(self, message: Message) -> None:
        self.sent.append(message)


@pytest.mark.anyio
async def test_router_unconsumed_request_stream_does_not_block_siblings() -> None:
    """A response whose `sse_writer` is not yet receiving must not park the router (#1764).

    Drives the routing layer directly (the production race does not reproduce
    on loopback), so this pins the router semantics, not the call sites.
    """
    transport = StreamableHTTPServerTransport(mcp_session_id="sid", is_json_response_enabled=False)
    streams = transport._request_streams
    async with transport.connect() as (_read_stream, write_stream):
        # Model two concurrent POSTs at the point _handle_post_request has
        # registered the per-request stream but A's sse_writer has not yet
        # reached its first receive().
        streams["A"] = anyio.create_memory_object_stream[EventMessage](REQUEST_STREAM_BUFFER_SIZE)
        streams["B"] = anyio.create_memory_object_stream[EventMessage](REQUEST_STREAM_BUFFER_SIZE)
        a_send, a_recv = streams["A"]
        b_reader = streams["B"][1]
        b_received = anyio.Event()

        async def consume_b() -> None:
            async with b_reader:
                await b_reader.receive()
                b_received.set()

        async def server_writes() -> None:
            await write_stream.send(SessionMessage(JSONRPCResponse(jsonrpc="2.0", id="A", result={})))
            await write_stream.send(SessionMessage(JSONRPCResponse(jsonrpc="2.0", id="B", result={})))

        async with anyio.create_task_group() as tg:
            tg.start_soon(consume_b)
            tg.start_soon(server_writes)
            with anyio.fail_after(5):
                await b_received.wait()
            # A's response was buffered for its (late) consumer, not dropped.
            assert a_send.statistics().current_buffer_used == 1
            await a_recv.aclose()
            await a_send.aclose()


@pytest.mark.anyio
async def test_priming_store_failure_leaves_no_per_request_state() -> None:
    """`EventStore.store_event` raising on the priming row must not leak per-request entries."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=False,
        event_store=_PrimingFailingStore(),
    )

    post = _AsgiPost(
        b'{"jsonrpc":"2.0","id":"req-1","method":"tools/list","params":{}}',
        [
            (b"accept", b"application/json, text/event-stream"),
            (b"content-type", b"application/json"),
            (b"mcp-protocol-version", b"2025-11-25"),
        ],
    )

    async with transport.connect() as (read_stream, _write_stream):
        async with anyio.create_task_group() as tg:
            tg.start_soon(transport.handle_request, post.scope, post.receive, post.send)
            with anyio.fail_after(5):
                forwarded = await read_stream.receive()
            assert isinstance(forwarded, Exception)
        # handle_request has returned; connect()'s finally (which clears
        # _request_streams unconditionally) has not yet run.
        assert transport._request_streams == {}
        assert transport._sse_stream_writers == {}

    assert post.sent[0]["type"] == "http.response.start"
    assert post.sent[0]["status"] == 500
    body = b"".join(m.get("body", b"") for m in post.sent if m["type"] == "http.response.body")
    assert b"backend unavailable" not in body


@pytest.mark.anyio
async def test_json_post_answers_500_when_session_terminates_mid_request() -> None:
    """A JSON-mode POST whose session is torn down before the handler answers gets a 500, not a stall."""
    transport = StreamableHTTPServerTransport(mcp_session_id="sid", is_json_response_enabled=True)
    post = _AsgiPost(
        b'{"jsonrpc":"2.0","id":"req-1","method":"tools/list","params":{}}',
        [
            (b"accept", b"application/json"),
            (b"content-type", b"application/json"),
            (b"mcp-session-id", b"sid"),
            (b"mcp-protocol-version", b"2025-11-25"),
        ],
    )

    async with transport.connect() as (read_stream, _write_stream):
        async with anyio.create_task_group() as tg:
            tg.start_soon(transport.handle_request, post.scope, post.receive, post.send)
            with anyio.fail_after(5):
                await read_stream.receive()  # the request reached the session; the POST is parked
            await transport.terminate()

    assert post.sent[0]["type"] == "http.response.start"
    assert post.sent[0]["status"] == 500


@pytest.mark.anyio
async def test_terminated_transport_answers_404() -> None:
    """A request that still reaches a transport after its session was terminated is answered 404."""
    transport = StreamableHTTPServerTransport(mcp_session_id="sid")
    post = _AsgiPost(
        b'{"jsonrpc":"2.0","id":"req-1","method":"ping"}',
        [(b"accept", b"application/json, text/event-stream"), (b"content-type", b"application/json")],
    )
    async with transport.connect():
        await transport.terminate()
        await transport.handle_request(post.scope, post.receive, post.send)

    assert post.sent[0]["type"] == "http.response.start"
    assert post.sent[0]["status"] == 404


@pytest.mark.anyio
async def test_a_response_produced_during_replay_reaches_the_resumed_stream() -> None:
    """SDK-defined: a response arriving after the replay snapshot cannot fall between replay and live delivery.

    A gated public EventStore and raw ASGI peer expose the handoff without depending on HTTP client scheduling.
    """
    snapshot_taken = anyio.Event()
    release_replay = anyio.Event()
    response_delivered = anyio.Event()
    disconnect = anyio.Event()
    progress = JSONRPCNotification(
        jsonrpc="2.0", method="notifications/progress", params={"progressToken": "call", "progress": 0.5, "total": 1}
    )
    response = JSONRPCResponse(jsonrpc="2.0", id="request", result={"value": "resumed"})
    wire: list[bytes] = []

    class SnapshotStore(EventStore):
        def __init__(self) -> None:
            self.events: list[tuple[StreamId, JSONRPCMessage | None]] = []

        async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
            self.events.append((stream_id, message))
            return str(len(self.events))

        async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
            cursor = int(last_event_id)
            stream_id, _ = self.events[cursor - 1]
            snapshot = tuple(self.events[cursor:])
            snapshot_taken.set()
            await release_replay.wait()
            for index, (_, message) in enumerate(snapshot, cursor + 1):
                assert message is not None
                await send_callback(EventMessage(message, str(index)))
            return stream_id

    store = SnapshotStore()
    last_event_id = await store.store_event("request", None)
    await store.store_event("request", progress)
    transport = StreamableHTTPServerTransport(mcp_session_id=None, event_store=store)
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/mcp",
        "query_string": b"",
        "headers": [
            (b"accept", b"text/event-stream"),
            (b"mcp-protocol-version", b"2025-11-25"),
            (b"last-event-id", last_event_id.encode()),
        ],
    }

    async def receive() -> Message:
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            assert message["status"] == 200
        else:
            body = message.get("body", b"")
            wire.append(body)
            if response.model_dump_json(by_alias=True, exclude_unset=True).encode() in body:
                response_delivered.set()

    with anyio.fail_after(5):
        async with transport.connect() as (_, write_stream), anyio.create_task_group() as tg:
            tg.start_soon(transport.handle_request, scope, receive, send)
            await snapshot_taken.wait()
            await write_stream.send(SessionMessage(response))
            await anyio.wait_all_tasks_blocked()
            release_replay.set()
            await response_delivered.wait()
            disconnect.set()

    received = httpx2.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=b"".join(wire),
        request=httpx2.Request("GET", "http://localhost/mcp"),
    )
    assert [
        jsonrpc_message_adapter.validate_json(event.data) for event in httpx2.EventSource(received) if event.data
    ] == [
        progress,
        response,
    ]


@pytest.mark.anyio
async def test_transport_shutdown_cancels_a_router_waiting_for_replay() -> None:
    """SDK-defined: a stalled replay cannot keep the session's response router alive after termination."""
    replay_started = anyio.Event()
    sent: list[Message] = []

    class BlockingStore(EventStore):
        async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
            return "cursor"

        async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
            replay_started.set()
            return await anyio.sleep_forever()

    store = BlockingStore()
    cursor = await store.store_event("request", None)
    transport = StreamableHTTPServerTransport(mcp_session_id=None, event_store=store)
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/mcp",
        "query_string": b"",
        "headers": [(b"accept", b"text/event-stream"), (b"last-event-id", cursor.encode())],
    }

    async def receive() -> Message:
        await anyio.sleep_forever()
        raise NotImplementedError

    async def send(message: Message) -> None:
        sent.append(message)

    with anyio.fail_after(5):
        async with anyio.create_task_group() as requests:
            async with transport.connect() as (_, write_stream):
                requests.start_soon(transport.handle_request, scope, receive, send)
                await replay_started.wait()
                await write_stream.send(SessionMessage(JSONRPCResponse(jsonrpc="2.0", id="request", result={})))
                await anyio.wait_all_tasks_blocked()
                await transport.terminate()
            requests.cancel_scope.cancel()

    assert transport.is_terminated
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 200


@pytest.mark.anyio
@pytest.mark.parametrize("json_response", [False, True], ids=["sse", "json"])
@pytest.mark.parametrize("pause_priming", [False, True], ids=["live", "priming"])
async def test_closing_a_replay_preserves_a_later_post_reusing_its_request_id(
    json_response: bool, pause_priming: bool
) -> None:
    """SDK-defined: a replay closes its own streams, not a later POST's streams for the same ID.

    A raw ASGI peer controls the old HTTP connection's lifetime after receiving its completed response.
    """
    replay_registered = anyio.Event()
    replay_finished = anyio.Event()
    post_finished = anyio.Event()
    replay_scope = anyio.CancelScope()
    request = JSONRPCRequest(jsonrpc="2.0", id="request", method="tools/list")
    previous = JSONRPCResponse(jsonrpc="2.0", id="request", result={"value": "previous"})
    expected = JSONRPCResponse(jsonrpc="2.0", id="request", result={"value": "current"})
    replay_wire: list[bytes] = []
    post_wire: list[bytes] = []

    class RecordingStore(EventStore):
        def __init__(self) -> None:
            self.events: list[tuple[StreamId, JSONRPCMessage | None]] = []

        async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
            self.events.append((stream_id, message))
            event_id = str(len(self.events))
            if len(self.events) == 3:
                replay_registered.set()
                if pause_priming:
                    await anyio.sleep_forever()
            return event_id

        async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
            assert last_event_id == "1"
            await send_callback(EventMessage(previous, "2"))
            return "request"

    store = RecordingStore()
    cursor = await store.store_event("request", None)
    await store.store_event("request", previous)
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None, event_store=store, is_json_response_enabled=json_response
    )
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/mcp",
        "query_string": b"",
        "headers": [
            (b"accept", b"application/json, text/event-stream"),
            (b"content-type", b"application/json"),
            (b"mcp-protocol-version", b"2025-11-25"),
        ],
    }

    async def get_receive() -> Message:
        await anyio.sleep_forever()
        raise NotImplementedError

    async def get_send(message: Message) -> None:
        if message["type"] == "http.response.body":
            replay_wire.append(message.get("body", b""))

    async def get() -> None:
        with replay_scope:
            await transport.handle_request(
                scope | {"headers": [*scope["headers"], (b"last-event-id", cursor.encode())]}, get_receive, get_send
            )
        replay_finished.set()

    async def post_send(message: Message) -> None:
        if message["type"] == "http.response.body":
            post_wire.append(message.get("body", b""))

    outgoing, incoming = anyio.create_memory_object_stream[Message](1)

    async def post() -> None:
        await transport.handle_request(scope | {"method": "POST"}, incoming.receive, post_send)
        post_finished.set()

    with anyio.fail_after(5):
        async with (
            outgoing,
            incoming,
            transport.connect() as (read_stream, write_stream),
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(get)
            await replay_registered.wait()
            await anyio.wait_all_tasks_blocked()
            assert previous.model_dump_json(by_alias=True, exclude_unset=True).encode() in b"".join(replay_wire)
            await outgoing.send(
                {"type": "http.request", "body": request.model_dump_json(by_alias=True, exclude_none=True).encode()}
            )
            tg.start_soon(post)
            forwarded = await read_stream.receive()
            assert isinstance(forwarded, SessionMessage)
            assert forwarded.message == request
            replay_scope.cancel()
            await replay_finished.wait()
            gc.collect()
            await write_stream.send(SessionMessage(expected))
            await post_finished.wait()

    if json_response:
        assert jsonrpc_message_adapter.validate_json(b"".join(post_wire)) == expected
    else:
        received = httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"".join(post_wire),
            request=httpx2.Request("POST", "http://localhost/mcp"),
        )
        assert [
            jsonrpc_message_adapter.validate_json(event.data) for event in httpx2.EventSource(received) if event.data
        ] == [expected]
    gc.collect()
