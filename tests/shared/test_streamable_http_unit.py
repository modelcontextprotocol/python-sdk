"""Focused unit tests for :mod:`mcp.client.streamable_http`."""

from __future__ import annotations

from collections.abc import AsyncIterator

import anyio
import pytest
from httpx import Timeout
from httpx_sse import ServerSentEvent

from mcp.client.streamable_http import (
    LAST_EVENT_ID,
    RequestContext,
    ResumptionError,
    StreamableHTTPTransport,
)
from mcp.shared.message import ClientMessageMetadata, SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCNotification, JSONRPCRequest, JSONRPCResponse


SessionMessageOrError = SessionMessage | Exception


@pytest.mark.anyio
async def test_handle_sse_event_initialization_sets_protocol_and_restores_id() -> None:
    """Initialization responses should update protocol version and preserve request IDs."""

    transport = StreamableHTTPTransport("http://example.test")
    send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessageOrError](10)

    initialization_payload = {
        "protocolVersion": "1.2",
        "capabilities": {},
        "serverInfo": {"name": "unit", "version": "0.0.0"},
    }
    response_message = JSONRPCMessage(
        JSONRPCResponse(jsonrpc="2.0", id="server-id", result=initialization_payload)
    )
    sse = ServerSentEvent(event="message", data=response_message.model_dump_json())

    async with send_stream, receive_stream:
        complete = await transport._handle_sse_event(  # noqa: SLF001 - exercising private helper
            sse,
            send_stream,
            original_request_id="original-id",
            is_initialization=True,
        )

        assert complete is True
        received = await receive_stream.receive()
        assert isinstance(received, SessionMessage)
        assert received.message.root.id == "original-id"
        assert transport.protocol_version == "1.2"


@pytest.mark.anyio
async def test_handle_sse_event_notification_invokes_resumption_callback() -> None:
    """Notifications should forward resumption tokens and keep the stream open."""

    transport = StreamableHTTPTransport("http://example.test")
    send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessageOrError](10)

    notification_message = JSONRPCMessage(
        JSONRPCNotification(jsonrpc="2.0", method="test/notification", params=None)
    )
    sse = ServerSentEvent(event="message", data=notification_message.model_dump_json(), id=" resume ")

    captured_token: list[str] = []

    async def on_resumption_token_update(token: str) -> None:
        captured_token.append(token)

    async with send_stream, receive_stream:
        complete = await transport._handle_sse_event(  # noqa: SLF001 - exercising private helper
            sse,
            send_stream,
            resumption_callback=on_resumption_token_update,
        )

        assert complete is False
        received = await receive_stream.receive()
        assert isinstance(received, SessionMessage)
        assert isinstance(received.message.root, JSONRPCNotification)
        assert captured_token == ["resume"]


class _FakeResponse:
    def __init__(self) -> None:
        self.raised = False
        self.closed = False

    def raise_for_status(self) -> None:
        self.raised = True

    async def aclose(self) -> None:
        self.closed = True


class _FakeEventSource:
    def __init__(self, events: list[ServerSentEvent], response: _FakeResponse | None = None) -> None:
        self._events = events
        self.response = response or _FakeResponse()

    async def __aenter__(self) -> "_FakeEventSource":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    async def aiter_sse(self) -> AsyncIterator[ServerSentEvent]:
        for event in self._events:
            yield event


@pytest.mark.anyio
async def test_handle_get_stream_processes_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """The GET stream helper should consume SSE events when a session exists."""

    transport = StreamableHTTPTransport("http://example.test")
    transport.session_id = "session-123"

    send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessageOrError](10)
    fake_events = [ServerSentEvent(event="message", data="{}")]

    captured_headers: dict[str, str] | None = None

    def fake_aconnect_sse(
        client: object, method: str, url: str, headers: dict[str, str], timeout: Timeout
    ) -> _FakeEventSource:
        nonlocal captured_headers
        captured_headers = headers
        assert method == "GET"
        assert url == "http://example.test"
        return _FakeEventSource(fake_events)

    call_count = 0

    async def fake_handle_sse_event(*args, **kwargs) -> bool:  # type: ignore[unused-argument]
        nonlocal call_count
        call_count += 1
        return True

    monkeypatch.setattr("mcp.client.streamable_http.aconnect_sse", fake_aconnect_sse)
    monkeypatch.setattr(
        StreamableHTTPTransport, "_handle_sse_event", fake_handle_sse_event
    )

    async with send_stream, receive_stream:
        await transport.handle_get_stream(object(), send_stream)

    assert call_count == 1
    assert captured_headers is not None
    assert captured_headers.get("mcp-session-id") == "session-123"


@pytest.mark.anyio
async def test_handle_resumption_request_requires_token() -> None:
    """Resumption requests without a token must fail fast."""

    transport = StreamableHTTPTransport("http://example.test")
    send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessageOrError](10)

    session_message = SessionMessage(
        JSONRPCMessage(JSONRPCRequest(jsonrpc="2.0", id="1", method="test"))
    )
    ctx = RequestContext(
        client=object(),
        headers={},
        session_id=None,
        session_message=session_message,
        metadata=ClientMessageMetadata(resumption_token=None),
        read_stream_writer=send_stream,
        sse_read_timeout=1.0,
    )

    async with send_stream, receive_stream:
        with pytest.raises(ResumptionError):
            await transport._handle_resumption_request(ctx)  # noqa: SLF001


@pytest.mark.anyio
async def test_handle_resumption_request_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resumption requests should forward the original ID and close the SSE response."""

    transport = StreamableHTTPTransport("http://example.test")
    transport.session_id = "session-123"
    send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessageOrError](10)

    metadata = ClientMessageMetadata(resumption_token=" token ")
    session_message = SessionMessage(
        JSONRPCMessage(
            JSONRPCRequest(jsonrpc="2.0", id="original", method="tool", params={})
        ),
        metadata=metadata,
    )
    ctx = RequestContext(
        client=object(),
        headers={"custom": "header"},
        session_id="session-123",
        session_message=session_message,
        metadata=metadata,
        read_stream_writer=send_stream,
        sse_read_timeout=1.0,
    )

    fake_events = [ServerSentEvent(event="message", data="{}") for _ in range(2)]
    fake_event_source = _FakeEventSource(fake_events)

    captured_headers: dict[str, str] | None = None

    def fake_aconnect_sse(
        client: object, method: str, url: str, headers: dict[str, str], timeout: Timeout
    ) -> _FakeEventSource:
        nonlocal captured_headers
        captured_headers = headers
        assert client is ctx.client
        assert method == "GET"
        assert url == "http://example.test"
        return fake_event_source

    call_args: list[dict[str, object]] = []

    async def fake_handle_sse_event(
        self,
        sse,
        read_stream_writer,
        original_request_id=None,
        resumption_callback=None,
        is_initialization=False,
    ) -> bool:
        call_args.append(
            {
                "original_request_id": original_request_id,
                "resumption_callback": resumption_callback,
            }
        )
        return len(call_args) >= 2

    monkeypatch.setattr("mcp.client.streamable_http.aconnect_sse", fake_aconnect_sse)
    monkeypatch.setattr(StreamableHTTPTransport, "_handle_sse_event", fake_handle_sse_event)

    async with send_stream, receive_stream:
        await transport._handle_resumption_request(ctx)  # noqa: SLF001

    assert captured_headers is not None
    assert captured_headers.get(LAST_EVENT_ID) == "token"
    assert fake_event_source.response.raised is True
    assert fake_event_source.response.closed is True
    assert call_args
    assert call_args[0]["original_request_id"] == "original"


@pytest.mark.anyio
async def test_handle_sse_response_closes_after_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    """SSE POST responses should stop reading once a response has been emitted."""

    transport = StreamableHTTPTransport("http://example.test")
    send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessageOrError](10)

    metadata = ClientMessageMetadata()
    session_message = SessionMessage(
        JSONRPCMessage(JSONRPCRequest(jsonrpc="2.0", id="42", method="ping")),
        metadata=metadata,
    )
    ctx = RequestContext(
        client=object(),
        headers={},
        session_id=None,
        session_message=session_message,
        metadata=metadata,
        read_stream_writer=send_stream,
        sse_read_timeout=1.0,
    )

    events = [ServerSentEvent(event="message", data="{}") for _ in range(2)]

    created_sources: list[_FakeEventSource] = []

    class FakeEventSourceFactory:
        def __call__(self, response: _FakeResponse) -> _FakeEventSource:
            source = _FakeEventSource(events, response)
            created_sources.append(source)
            return source

    fake_response = _FakeResponse()

    async def fake_handle_sse_event(*args, **kwargs) -> bool:  # type: ignore[unused-argument]
        fake_handle_sse_event.call_count += 1
        return fake_handle_sse_event.call_count >= 2

    fake_handle_sse_event.call_count = 0

    monkeypatch.setattr("mcp.client.streamable_http.EventSource", FakeEventSourceFactory())
    monkeypatch.setattr(StreamableHTTPTransport, "_handle_sse_event", fake_handle_sse_event)

    async with send_stream, receive_stream:
        await transport._handle_sse_response(fake_response, ctx, is_initialization=True)

    assert fake_handle_sse_event.call_count == 2
    assert created_sources and created_sources[0].response is fake_response
    assert fake_response.closed is True

