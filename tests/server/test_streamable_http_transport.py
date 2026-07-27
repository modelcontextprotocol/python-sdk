"""Behaviour of the StreamableHTTP server transport's per-request dispatch.

Each POSTed request is served by its own response channel and a session-scoped
correlator; these tests pin the parts of that lifecycle a real client can hit
that the transport-agnostic interaction matrix does not reach.
"""

import anyio
import pytest
from httpx2 import EventSource
from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
    TextContent,
)
from starlette.types import Message, Scope

from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http import (
    EventCallback,
    EventId,
    EventStore,
    StreamableHTTPServerTransport,
    StreamId,
    _HTTPRequestDispatchContext,  # pyright: ignore[reportPrivateUsage]
    _MessageChannel,  # pyright: ignore[reportPrivateUsage]
)
from mcp.shared._correlation import RequestCorrelator
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.message import ServerMessageMetadata
from mcp.shared.transport_context import TransportContext
from tests.interaction._connect import base_headers, initialize_via_http, mounted_app, parse_sse_messages
from tests.interaction.transports._event_store import SequencedEventStore

pytestmark = pytest.mark.anyio


class _PrimingFailingStore(EventStore):
    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        raise RuntimeError("backend unavailable")

    async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
        raise NotImplementedError


class _StreamFailingStore(SequencedEventStore):
    """A store that breaks for every message on request ``42``'s stream (its priming row aside)."""

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        if stream_id == "42" and message is not None:
            raise RuntimeError("backend fell over")
        return await super().store_event(stream_id, message)


def _tools_call(request_id: int, name: str, arguments: dict[str, object]) -> str:
    return JSONRPCRequest(
        jsonrpc="2.0", id=request_id, method="tools/call", params={"name": name, "arguments": arguments}
    ).model_dump_json(by_alias=True, exclude_none=True)


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
    payload = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert b"backend unavailable" not in payload


async def test_terminating_a_session_ends_its_in_flight_request_streams_and_cancels_the_handlers() -> None:
    """DELETE while a call is running closes that call's SSE stream and cancels its handler."""
    started = anyio.Event()
    cancelled = anyio.Event()

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        started.set()
        try:
            await anyio.sleep_forever()
        finally:
            cancelled.set()
        raise NotImplementedError  # unreachable: the handler is cancelled while sleeping

    server = Server("terminating", on_call_tool=call_tool)

    async with mounted_app(server) as (http, _):
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            async with http.stream(
                "POST", "/mcp", content=_tools_call(1, "wait", {}), headers=base_headers(session_id=session_id)
            ) as response:
                assert response.status_code == 200
                await started.wait()
                delete = await http.delete("/mcp", headers=base_headers(session_id=session_id))
                assert delete.status_code == 200
                # Termination closes the request's stream, so the read ends here.
                events = [event async for event in EventSource(response)]
                await cancelled.wait()
            follow_up = await http.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
                headers=base_headers(session_id=session_id),
            )

    assert all(not isinstance(message, JSONRPCResponse) for message in parse_sse_messages(events))
    assert follow_up.status_code == 404


async def test_a_posted_progress_notification_reaches_the_servers_pending_request() -> None:
    """A client POSTs notifications/progress for a request the server sent it; the server's callback receives it.

    The elicitation request rides the tool call's own SSE stream (related to it); the progress
    notification and the answer arrive as separate POSTs and are correlated back to the pending
    request by the token / id the server minted.
    """
    reports: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        reports.append((progress, total, message))

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        result = await ctx.session.send_request(
            ElicitRequest(
                params=ElicitRequestFormParams(message="ok?", requested_schema={"type": "object", "properties": {}})
            ),
            ElicitResult,
            metadata=ServerMessageMetadata(related_request_id=ctx.request_id),
            progress_callback=on_progress,
        )
        return CallToolResult(content=[TextContent(text=result.action)])

    server = Server("progressive", on_call_tool=call_tool)

    async with mounted_app(server) as (http, _):
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            async with http.stream(  # pragma: no branch
                "POST", "/mcp", content=_tools_call(1, "ask", {}), headers=base_headers(session_id=session_id)
            ) as response:
                assert response.status_code == 200
                events = aiter(EventSource(response))
                elicit_event = await anext(events)
                elicit = JSONRPCRequest.model_validate_json(elicit_event.data)
                assert elicit.method == "elicitation/create"
                assert elicit.params is not None
                token = elicit.params["_meta"]["progressToken"]
                progress = await http.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "method": "notifications/progress",
                        "params": {"progressToken": token, "progress": 0.5, "total": 1.0, "message": "half"},
                    },
                    headers=base_headers(session_id=session_id),
                )
                assert progress.status_code == 202
                answer = await http.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": elicit.id, "result": {"action": "accept", "content": {}}},
                    headers=base_headers(session_id=session_id),
                )
                assert answer.status_code == 202
                result_event = await anext(events)
    result = JSONRPCResponse.model_validate_json(result_event.data)
    assert result.result["content"] == [{"type": "text", "text": "accept"}]
    assert reports == [(0.5, 1.0, "half")]


async def test_an_event_store_failure_mid_request_costs_only_that_request() -> None:
    """A store that raises for a request's stream fails that request cleanly, never the session.

    Neither request 42's result nor the error frame reporting the failure can be stored, so its
    stream ends without a terminal frame instead of hanging; request 43 on the same session is
    served normally.
    """

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        return CallToolResult(content=[TextContent(text=params.name)])

    server = Server("resilient", on_call_tool=call_tool)

    async with mounted_app(server, event_store=_StreamFailingStore(), retry_interval=0) as (http, _):
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            async with http.stream(
                "POST", "/mcp", content=_tools_call(42, "first", {}), headers=base_headers(session_id=session_id)
            ) as failing:
                assert failing.status_code == 200
                failing_events = [event async for event in EventSource(failing)]
            async with http.stream(  # pragma: no branch
                "POST", "/mcp", content=_tools_call(43, "second", {}), headers=base_headers(session_id=session_id)
            ) as healthy:
                assert healthy.status_code == 200
                healthy_events = [event async for event in EventSource(healthy)]

    # Request 42's stream carried its priming event and then ended with no terminal frame.
    assert parse_sse_messages(failing_events) == []
    (second,) = [message for message in parse_sse_messages(healthy_events) if isinstance(message, JSONRPCResponse)]
    assert second.id == 43
    assert second.result["content"] == [{"type": "text", "text": "second"}]


async def test_concurrent_posts_reusing_a_request_id_each_receive_their_own_response() -> None:
    """Two concurrent requests sharing a JSON-RPC id are answered on their own POST streams.

    Each POST owns its response channel, so the second registration does not steal or clobber
    the first's stream (the session-level entry only serves close/replay lookup).
    """
    slow_started = anyio.Event()
    release = anyio.Event()

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "slow":
            slow_started.set()
            await release.wait()
        return CallToolResult(content=[TextContent(text=params.name)])

    server = Server("dupes", on_call_tool=call_tool)
    results: dict[str, JSONRPCResponse] = {}

    async with mounted_app(server) as (http, _):
        session_id = await initialize_via_http(http)

        async def post(name: str) -> None:
            async with http.stream(
                "POST", "/mcp", content=_tools_call(7, name, {}), headers=base_headers(session_id=session_id)
            ) as response:
                events = [event async for event in EventSource(response)]
            (message,) = parse_sse_messages(events)
            assert isinstance(message, JSONRPCResponse)
            results[name] = message

        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch
                tg.start_soon(post, "slow")
                await slow_started.wait()
                await post("fast")
                release.set()

    assert results["fast"].result["content"] == [{"type": "text", "text": "fast"}]
    assert results["slow"].result["content"] == [{"type": "text", "text": "slow"}]
    assert {results["fast"].id, results["slow"].id} == {7}


def test_detaching_a_stale_attachment_does_not_evict_the_newer_one() -> None:
    """A response that finishes after a Last-Event-ID reconnect re-attached must not knock the newer
    attachment off its channel."""
    channel = _MessageChannel("1", None)
    stale_reader = channel.attach()
    channel.detach()  # e.g. close_sse_stream()
    fresh_reader = channel.attach()  # the client's reconnect re-attached
    channel.detach(stale_reader)  # the stale response's cleanup lands late
    assert channel.attached
    channel.detach(fresh_reader)
    assert not channel.attached
    stale_reader.close()
    fresh_reader.close()


def test_closing_streams_for_unknown_requests_is_a_no_op() -> None:
    """`close_sse_stream` / `close_standalone_sse_stream` with nothing open do nothing."""
    transport = StreamableHTTPServerTransport("sid")
    transport.close_sse_stream("no-such-request")
    transport.close_standalone_sse_stream()


async def test_a_transport_not_bound_to_a_server_refuses_to_handle_requests() -> None:
    """The transport is created by the session manager; driving one built without a server fails loudly."""
    transport = StreamableHTTPServerTransport("sid")
    scope: Scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []}

    async def receive() -> Message:
        raise NotImplementedError

    async def send(message: Message) -> None:
        raise NotImplementedError

    with pytest.raises(RuntimeError, match="not bound to a server"):
        await transport.handle_request(scope, receive, send)


async def test_a_closed_request_context_drops_notifications_and_refuses_requests() -> None:
    """Once the handler has returned, its context stops accepting output (a background task can't
    write onto a finished request's stream)."""
    channel = _MessageChannel("1", None)
    dctx = _HTTPRequestDispatchContext(
        transport=TransportContext(kind="streamable-http", can_send_request=True),
        _corr=RequestCorrelator(),
        _channel=channel,
        _request_id=1,
    )
    assert dctx.can_send_request

    dctx.close()

    await dctx.notify("notifications/message", {"level": "info", "data": "too late"})
    assert not channel.finished.is_set()
    with pytest.raises(NoBackChannelError):
        await dctx.send_raw_request("ping", None)
