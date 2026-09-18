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


@pytest.fixture(scope="module", params=["asyncio", "trio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    return request.param


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
@pytest.mark.parametrize("terminate", [False, True], ids=["context-exit", "terminated"])
@pytest.mark.parametrize("wait_for_router", [False, True], ids=["after-send", "queued"])
async def test_transport_shutdown_cancels_a_router_waiting_for_replay(terminate: bool, wait_for_router: bool) -> None:
    """SDK-defined: shutdown releases a blocked router, and its late replay cannot open a dead stream."""
    replay_started = anyio.Event()
    release_replay = anyio.Event()
    replay_finished = anyio.Event()
    sent: list[Message] = []

    class BlockingStore(EventStore):
        async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
            return "cursor"

        async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
            replay_started.set()
            await release_replay.wait()
            return "request"

    store = BlockingStore()
    cursor = await store.store_event("request", None)
    transport = StreamableHTTPServerTransport(mcp_session_id=None, event_store=store)
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/mcp",
        "query_string": b"",
        "headers": [
            (b"accept", b"text/event-stream"),
            (b"last-event-id", cursor.encode()),
            (b"mcp-protocol-version", b"2025-11-25"),
        ],
    }

    async def receive() -> Message:
        await anyio.sleep_forever()
        raise NotImplementedError

    async def send(message: Message) -> None:
        sent.append(message)

    async def replay() -> None:
        await transport.handle_request(scope, receive, send)
        replay_finished.set()

    with anyio.fail_after(5):
        async with anyio.create_task_group() as requests:
            async with transport.connect() as (_, write_stream):
                requests.start_soon(replay)
                await replay_started.wait()
                await anyio.wait_all_tasks_blocked()
                await write_stream.send(SessionMessage(JSONRPCResponse(jsonrpc="2.0", id="request", result={})))
                if wait_for_router:
                    await anyio.wait_all_tasks_blocked()
                if terminate:
                    await transport.terminate()
            release_replay.set()
            await replay_finished.wait()

    assert transport.is_terminated is terminate
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 200
    assert b"".join(message.get("body", b"") for message in sent) == b""


@pytest.mark.anyio
@pytest.mark.parametrize("window", ["lock", "hook"])
async def test_termination_during_replay_setup_ends_the_response_without_priming(window: str) -> None:
    """SDK-defined: termination wins over a replay waiting for the lock or its event-store hook."""
    storing = anyio.Event()
    replay_started = anyio.Event()
    headers_sent = anyio.Event()
    release = anyio.Event()
    replay_finished = anyio.Event()
    sent: list[Message] = []
    response = JSONRPCResponse(jsonrpc="2.0", id="request", result={})

    class GatedStore(EventStore):
        async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
            if window == "lock":
                storing.set()
                await release.wait()
            return "stored"

        async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
            replay_started.set()
            await release.wait()
            return "request"

    transport = StreamableHTTPServerTransport(None, event_store=GatedStore())
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/mcp",
        "query_string": b"",
        "headers": [
            (b"accept", b"text/event-stream"),
            (b"last-event-id", b"cursor"),
            (b"mcp-protocol-version", b"2025-11-25"),
        ],
    }

    async def receive() -> Message:
        await anyio.sleep_forever()
        raise NotImplementedError

    async def send(message: Message) -> None:
        sent.append(message)
        if message["type"] == "http.response.start":
            assert message["status"] == 200
            headers_sent.set()

    async def replay() -> None:
        await transport.handle_request(scope, receive, send)
        replay_finished.set()

    with anyio.fail_after(5):
        async with transport.connect() as (_, write_stream), anyio.create_task_group() as requests:
            if window == "lock":
                await write_stream.send(SessionMessage(response))
                await storing.wait()
            requests.start_soon(replay)
            await headers_sent.wait()
            if window == "hook":
                await replay_started.wait()
                await write_stream.send(SessionMessage(response))
            await anyio.wait_all_tasks_blocked()
            await transport.terminate()
            release.set()
            await replay_finished.wait()
            await anyio.wait_all_tasks_blocked()

    assert replay_started.is_set() is (window == "hook")
    assert b"".join(message.get("body", b"") for message in sent) == b""


@pytest.mark.anyio
@pytest.mark.parametrize("history_size", [0, 16, 1024 * 1024 + 1], ids=["priming", "memory", "spilled"])
@pytest.mark.parametrize("disconnect_early", [False, True], ids=["drain", "disconnect"])
async def test_a_blocked_replay_does_not_prevent_a_sibling_response(history_size: int, disconnect_early: bool) -> None:
    """SDK-defined: a replay's network backpressure cannot hold the event-store lock.

    The raw ASGI peer blocks response headers, making the network stall deterministic without HTTPX2.
    """
    replay_started = anyio.Event()
    headers_sent = anyio.Event()
    release_headers = anyio.Event()
    priming_received = anyio.Event()
    tail_received = anyio.Event()
    disconnect = anyio.Event()
    post_finished = anyio.Event()
    history = JSONRPCNotification(
        jsonrpc="2.0",
        method="notifications/progress",
        params={"progressToken": "p", "progress": 0.5, "message": "x" * history_size},
    )
    tail = JSONRPCResponse(jsonrpc="2.0", id="replay", result={"done": True})
    sibling = JSONRPCResponse(jsonrpc="2.0", id="sibling", result={"ok": True})
    chunks: list[bytes] = []

    class ReplayStore(EventStore):
        def __init__(self) -> None:
            self.events: list[JSONRPCMessage | None] = []

        async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
            self.events.append(message)
            return str(len(self.events))

        async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
            assert last_event_id == "cursor"
            replay_started.set()
            if history_size:
                await send_callback(EventMessage(history, "historical"))
            return "replay"

    transport = StreamableHTTPServerTransport(None, is_json_response_enabled=True, event_store=ReplayStore())
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/mcp",
        "query_string": b"",
        "headers": [
            (b"accept", b"text/event-stream"),
            (b"last-event-id", b"cursor"),
            (b"mcp-protocol-version", b"2025-11-25"),
        ],
    }

    async def receive() -> Message:
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            assert message["status"] == 200
            headers_sent.set()
            await release_headers.wait()
        elif body := message.get("body", b""):
            assert body.endswith(b"\r\n\r\n")
            chunks.append(body)
            if body.endswith(b"data: \r\n\r\n"):
                priming_received.set()
            if tail.model_dump_json(by_alias=True, exclude_unset=True).encode() in body:
                tail_received.set()

    post = _AsgiPost(
        b'{"jsonrpc":"2.0","id":"sibling","method":"tools/list"}',
        [(b"accept", b"application/json"), (b"content-type", b"application/json")],
    )

    async def run_post() -> None:
        await transport.handle_request(post.scope, post.receive, post.send)
        post_finished.set()

    with anyio.fail_after(5):
        async with transport.connect() as (read_stream, write_stream):
            async with anyio.create_task_group() as requests:
                requests.start_soon(transport.handle_request, scope, receive, send)
                await headers_sent.wait()
                await replay_started.wait()
                requests.start_soon(run_post)
                incoming = await read_stream.receive()
                assert isinstance(incoming, SessionMessage)
                assert incoming.message == JSONRPCRequest(jsonrpc="2.0", id="sibling", method="tools/list")
                await write_stream.send(SessionMessage(sibling))
                await post_finished.wait()
                assert (
                    jsonrpc_message_adapter.validate_json(b"".join(message.get("body", b"") for message in post.sent))
                    == sibling
                )
                if disconnect_early:
                    disconnect.set()
                else:
                    release_headers.set()
                    await priming_received.wait()
                    await write_stream.send(SessionMessage(tail))
                    await tail_received.wait()
                    transport.close_sse_stream(tail.id)
            await transport.terminate()

    gc.collect()
    if disconnect_early:
        assert chunks == []
        return
    received = httpx2.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=b"".join(chunks),
        request=httpx2.Request("GET", "http://localhost/mcp"),
    )
    events = list(httpx2.EventSource(received))
    assert [jsonrpc_message_adapter.validate_json(event.data) for event in events if event.data] == (
        [history, tail] if history_size else [tail]
    )
    assert events[-2].data == ""
    assert events[-1].id != events[-2].id


@pytest.mark.anyio
@pytest.mark.parametrize("wait_for_store", [False, True], ids=["after-send", "during-store"])
async def test_normal_transport_exit_waits_for_an_active_event_store_write(wait_for_store: bool) -> None:
    """SDK-defined: normal session teardown finishes an accepted event-store write instead of cancelling it."""
    storing = anyio.Event()
    release = anyio.Event()
    exited = anyio.Event()
    response = JSONRPCResponse(jsonrpc="2.0", id="last", result={"done": True})
    stored: list[JSONRPCMessage | None] = []

    class GatedStore(EventStore):
        async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
            storing.set()
            await release.wait()
            stored.append(message)
            return "committed"

        async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
            raise NotImplementedError

    transport = StreamableHTTPServerTransport(None, event_store=GatedStore())

    async def run_session() -> None:
        async with transport.connect() as (_, write_stream):
            await write_stream.send(SessionMessage(response))
            if wait_for_store:
                await storing.wait()
        exited.set()

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(run_session)
            await storing.wait()
            await anyio.wait_all_tasks_blocked()
            try:
                assert not exited.is_set()
            finally:
                release.set()
            await exited.wait()
    assert stored == [response]


@pytest.mark.anyio
async def test_caller_cancellation_still_interrupts_an_event_store_write() -> None:
    """SDK-defined: draining a store on normal exit does not shield it against caller cancellation."""
    storing = anyio.Event()
    stopped = anyio.Event()

    class GatedStore(EventStore):
        async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
            try:
                with anyio.fail_after(5):
                    storing.set()
                    await anyio.sleep_forever()
            finally:
                stopped.set()
            raise NotImplementedError

        async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
            raise NotImplementedError

    transport = StreamableHTTPServerTransport(None, event_store=GatedStore())

    async def run_session() -> None:
        async with transport.connect() as (_, write_stream):
            await write_stream.send(SessionMessage(JSONRPCResponse(jsonrpc="2.0", id="last", result={})))
            await anyio.sleep_forever()

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(run_session)
            await storing.wait()
            tasks.cancel_scope.cancel()
    assert stopped.is_set()


@pytest.mark.anyio
@pytest.mark.parametrize("json_response", [False, True], ids=["sse", "json"])
@pytest.mark.parametrize("pause_priming", [False, True], ids=["live", "priming"])
async def test_closing_a_replay_preserves_a_later_post_reusing_its_request_id(
    json_response: bool, pause_priming: bool
) -> None:
    """SDK-defined: a replay closes its own streams, not a later POST's streams for the same ID.

    A raw ASGI peer controls the old HTTP connection's lifetime after the original request has completed.
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
            if not pause_priming:
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
