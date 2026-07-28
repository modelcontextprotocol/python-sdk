"""Regression coverage for the StreamableHTTP per-session response router."""

import anyio
import pytest
from mcp_types import JSONRPCMessage, JSONRPCResponse
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
