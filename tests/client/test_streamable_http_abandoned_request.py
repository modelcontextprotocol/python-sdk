"""Deterministic regression tests for abandoned-request resolution (#3441).

When a request's response can never arrive - the server answers the POST
with 202 Accepted, the per-request SSE stream ends without a response
event, or reconnection attempts are exhausted - the v1.x transport must
resolve the pending request with a synthesized JSONRPCError instead of
parking the caller until its own timeout fires.
"""

from collections.abc import AsyncIterator

import anyio
import httpx
import pytest
from mcp.shared.message import SessionMessage
from mcp.types import (
    CONNECTION_CLOSED,
    INVALID_REQUEST,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
)

from mcp.client.streamable_http import (
    MAX_RECONNECTION_ATTEMPTS,
    RequestContext,
    StreamableHTTPTransport,
)


def _make_request_context(
    client: httpx.AsyncClient,
    message: JSONRPCMessage,
    read_stream_writer,
) -> RequestContext:
    session_message = SessionMessage(message)
    return RequestContext(
        client=client,
        session_id=None,
        session_message=session_message,
        metadata=None,
        read_stream_writer=read_stream_writer,
    )


def _request(id_: str) -> JSONRPCMessage:
    return JSONRPCMessage(JSONRPCRequest(jsonrpc="2.0", id=id_, method="tools/call", params={}))


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
async def test_non_resumable_sse_drop_resolves_request_with_error() -> None:
    """A per-request SSE stream that dies having carried no event ids can never
    deliver its response; the transport resolves the waiter with CONNECTION_CLOSED
    instead of hanging forever."""
    transport = StreamableHTTPTransport("http://test/mcp")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=_DyingSSEStream())

    streams = anyio.create_memory_object_stream(4)
    try:
        write_stream, read_stream = streams
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ctx = _make_request_context(client, _request("req-sse"), write_stream)
            with anyio.fail_after(5):
                await transport._handle_post_request(ctx)
                reply = await read_stream.receive()
    finally:
        write_stream.close()
        read_stream.close()

    assert isinstance(reply.message.root, JSONRPCError)
    assert reply.message.root.id == "req-sse"
    assert reply.message.root.error.code == CONNECTION_CLOSED


@pytest.mark.anyio
async def test_post_answered_with_202_resolves_request_with_error() -> None:
    """A request answered with 202 Accepted will never receive a response body;
    the transport resolves the waiter with INVALID_REQUEST instead of hanging."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202)

    transport = StreamableHTTPTransport("http://test/mcp")
    streams = anyio.create_memory_object_stream(4)
    try:
        write_stream, read_stream = streams
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ctx = _make_request_context(client, _request("req-202"), write_stream)
            with anyio.fail_after(5):
                await transport._handle_post_request(ctx)
                reply = await read_stream.receive()
    finally:
        write_stream.close()
        read_stream.close()

    assert isinstance(reply.message.root, JSONRPCError)
    assert reply.message.root.id == "req-202"
    assert reply.message.root.error.code == INVALID_REQUEST


@pytest.mark.anyio
async def test_post_answered_with_202_does_not_resolve_notifications() -> None:
    """Notifications have no waiter to resolve; a 202 answer must not inject an
    error into the read stream for them."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202)

    transport = StreamableHTTPTransport("http://test/mcp")
    notification = JSONRPCMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized"))
    streams = anyio.create_memory_object_stream(4)
    try:
        write_stream, read_stream = streams
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ctx = _make_request_context(client, notification, write_stream)
            with anyio.move_on_after(1):
                await transport._handle_post_request(ctx)
                await read_stream.receive()
                pytest.fail("a notification must not be resolved with an error")
    finally:
        write_stream.close()
        read_stream.close()


@pytest.mark.anyio
async def test_exhausted_reconnection_attempts_resolve_request_with_error() -> None:
    """When reconnection attempts are exhausted for a request whose SSE stream
    keeps dying, the transport resolves the waiter with CONNECTION_CLOSED."""
    transport = StreamableHTTPTransport("http://test/mcp")

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        pytest.fail("exhausted reconnection must resolve without further HTTP calls")

    streams = anyio.create_memory_object_stream(4)
    try:
        write_stream, read_stream = streams
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ctx = _make_request_context(client, _request("req-ex"), write_stream)
            with anyio.fail_after(5):
                await transport._handle_reconnection(
                    ctx,
                    last_event_id="1",
                    retry_interval_ms=1,
                    attempt=MAX_RECONNECTION_ATTEMPTS,
                )
                reply = await read_stream.receive()
    finally:
        write_stream.close()
        read_stream.close()

    assert isinstance(reply.message.root, JSONRPCError)
    assert reply.message.root.id == "req-ex"
    assert reply.message.root.error.code == CONNECTION_CLOSED
