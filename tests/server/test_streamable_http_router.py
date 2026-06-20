"""Regression coverage for the StreamableHTTP per-session response router."""

import anyio
import pytest

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
from mcp.types import JSONRPCMessage, JSONRPCResponse


class _OrderTrackingStore(EventStore):
    def __init__(self) -> None:
        self.stored: list[tuple[StreamId, JSONRPCMessage | None]] = []

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        self.stored.append((stream_id, message))
        return str(len(self.stored))

    async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
        raise NotImplementedError


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
async def test_priming_event_is_stored_before_any_routed_message() -> None:
    """`_mint_priming_event` is awaited before the request is dispatched, so the
    priming row precedes every `message_router` store for that stream regardless
    of when `sse_writer` is scheduled.
    """
    store = _OrderTrackingStore()
    transport = StreamableHTTPServerTransport(mcp_session_id="sid", is_json_response_enabled=False, event_store=store)
    streams = transport._request_streams

    async with transport.connect() as (_read_stream, write_stream):
        # POST handler step: mint priming for "A" before dispatch.
        priming = await transport._mint_priming_event("A", "2025-11-25")
        assert priming is not None
        streams["A"] = anyio.create_memory_object_stream[EventMessage](REQUEST_STREAM_BUFFER_SIZE)
        a_send, a_recv = streams["A"]

        # Server emits 5 messages for "A" with no sse_writer scheduled. Each
        # write_stream.send() rendezvous-hands to message_router, which stores
        # then deposits into A's buffer; reading them back proves the router
        # has finished storing.
        for i in range(5):
            await write_stream.send(SessionMessage(JSONRPCResponse(jsonrpc="2.0", id="A", result={"n": i})))
        with anyio.fail_after(5):
            for _ in range(5):
                await a_recv.receive()
        await a_recv.aclose()
        await a_send.aclose()

    assert store.stored[0] == ("A", None)
    assert [sid for sid, _ in store.stored] == ["A"] * 6
    assert all(msg is not None for _, msg in store.stored[1:])
