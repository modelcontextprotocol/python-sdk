import contextlib

import anyio
import httpx
import pytest
from httpx_sse import ServerSentEvent

from mcp.client.streamable_http import RequestContext, StreamableHTTPTransport
from mcp.shared.message import ClientMessageMetadata, SessionMessage
from mcp.types import JSONRPCRequest


class _RaiseEventSource:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    async def aiter_sse(self):
        yield ServerSentEvent(event="message", data="", id=None, retry=None)
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_handle_sse_response_closes_response_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = False

    async def spy_aclose() -> None:
        nonlocal closed
        closed = True

    response = httpx.Response(200, headers={"content-type": "text/event-stream"})
    response.aclose = spy_aclose  # type: ignore[method-assign]

    monkeypatch.setattr("mcp.client.streamable_http.EventSource", _RaiseEventSource)

    send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    async with send_stream, receive_stream:
        transport = StreamableHTTPTransport("http://example.invalid/mcp")
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
            ctx = RequestContext(
                client=client,
                session_id=None,
                session_message=SessionMessage(JSONRPCRequest(method="initialize", params={}, jsonrpc="2.0", id=1)),
                metadata=ClientMessageMetadata(),
                read_stream_writer=send_stream,
            )
            await transport._handle_sse_response(response, ctx)

    assert closed


@pytest.mark.anyio
async def test_handle_resumption_request_closes_response_when_aconnect_sse_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextlib.asynccontextmanager
    async def fake_aconnect_sse(*_args, **_kwargs):
        raise RuntimeError("connect failed")
        yield

    monkeypatch.setattr("mcp.client.streamable_http.aconnect_sse", fake_aconnect_sse)

    send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    async with send_stream, receive_stream:
        transport = StreamableHTTPTransport("http://example.invalid/mcp")
        metadata = ClientMessageMetadata(resumption_token="1")
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
            ctx = RequestContext(
                client=client,
                session_id=None,
                session_message=SessionMessage(JSONRPCRequest(method="initialize", params={}, jsonrpc="2.0", id=1)),
                metadata=metadata,
                read_stream_writer=send_stream,
            )

            with pytest.raises(RuntimeError, match="connect failed"):
                await transport._handle_resumption_request(ctx)


@pytest.mark.anyio
async def test_handle_resumption_request_closes_response_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = False

    async def spy_aclose() -> None:
        nonlocal closed
        closed = True

    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        request=httpx.Request("GET", "http://example.invalid/mcp"),
    )
    response.aclose = spy_aclose  # type: ignore[method-assign]

    @contextlib.asynccontextmanager
    async def fake_aconnect_sse(*_args, **_kwargs):
        yield _RaiseEventSource(response)

    monkeypatch.setattr("mcp.client.streamable_http.aconnect_sse", fake_aconnect_sse)

    send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    async with send_stream, receive_stream:
        transport = StreamableHTTPTransport("http://example.invalid/mcp")
        metadata = ClientMessageMetadata(resumption_token="1")
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
            ctx = RequestContext(
                client=client,
                session_id=None,
                session_message=SessionMessage(JSONRPCRequest(method="initialize", params={}, jsonrpc="2.0", id=1)),
                metadata=metadata,
                read_stream_writer=send_stream,
            )

            with pytest.raises(RuntimeError, match="boom"):
                await transport._handle_resumption_request(ctx)

    assert closed
