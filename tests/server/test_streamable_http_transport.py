"""Failure handling in the StreamableHTTP server transport's per-request dispatch."""

import anyio
import pytest
from mcp_types import JSONRPCMessage
from starlette.types import Message, Scope

from mcp.server import Server
from mcp.server.streamable_http import (
    EventCallback,
    EventId,
    EventStore,
    StreamableHTTPServerTransport,
    StreamId,
)


class _PrimingFailingStore(EventStore):
    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        raise RuntimeError("backend unavailable")

    async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
        raise NotImplementedError


@pytest.mark.anyio
async def test_priming_store_failure_returns_500_without_leaking_per_request_state() -> None:
    """`EventStore.store_event` raising on the priming row yields a 500 with no leaked state or backend text.

    The priming row is minted before any per-request state exists, so a failing
    store leaves nothing to clean up and its exception text never reaches the wire.
    """
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=False,
        event_store=_PrimingFailingStore(),
        app=Server("priming-failure"),
        lifespan_state={},
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

    with anyio.fail_after(5):
        await transport.handle_request(scope, receive, asgi_send)

    assert transport._channels == {}  # pyright: ignore[reportPrivateUsage]
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 500
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert b"backend unavailable" not in body
