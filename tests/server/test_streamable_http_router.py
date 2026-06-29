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


@pytest.mark.anyio
async def test_router_unconsumed_request_stream_does_not_block_siblings() -> None:
    """Regression for #1764; drives the router directly: the production race does not reproduce on loopback."""
    transport = StreamableHTTPServerTransport(mcp_session_id="sid", is_json_response_enabled=False)
    streams = transport._request_streams
    async with transport.connect() as (_read_stream, write_stream):
        # As if _handle_post_request registered both streams but A's sse_writer hasn't reached its first receive().
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
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=False,
        event_store=_PrimingFailingStore(),
    )

    body = b'{"jsonrpc":"2.0","id":"req-1","method":"tools/list","params":{}}'
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "query_string": b"",
        "headers": [
            (b"accept", b"application/json, text/event-stream"),
            (b"content-type", b"application/json"),
            (b"mcp-protocol-version", b"2025-11-25"),
        ],
    }
    body_sent = False

    async def receive() -> Message:
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        raise NotImplementedError

    sent: list[Message] = []

    async def asgi_send(message: Message) -> None:
        sent.append(message)

    async with transport.connect() as (read_stream, _write_stream):
        async with anyio.create_task_group() as tg:
            tg.start_soon(transport.handle_request, scope, receive, asgi_send)
            with anyio.fail_after(5):
                forwarded = await read_stream.receive()
            assert isinstance(forwarded, Exception)
        # handle_request returned but connect()'s finally (which clears _request_streams unconditionally) hasn't yet.
        assert transport._request_streams == {}
        assert transport._sse_stream_writers == {}

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 500
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert b"backend unavailable" not in body
