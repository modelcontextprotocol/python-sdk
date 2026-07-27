"""Behaviour of the StreamableHTTP server transport's per-request dispatch.

Each POSTed request is served by its own response channel and a session-scoped
correlator; these tests pin the parts of that lifecycle a real client can hit
that the transport-agnostic interaction matrix does not reach.
"""

from typing import Any
from unittest.mock import MagicMock

import anyio
import anyio.lowlevel
import pytest
from httpx2 import EventSource
from mcp_types import (
    CONNECTION_CLOSED,
    INVALID_REQUEST,
    CallToolRequestParams,
    CallToolResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    TextContent,
)
from starlette.requests import Request
from starlette.types import Message, Scope

from mcp.server import Server, ServerRequestContext
from mcp.server.context import CallNext, HandlerResult
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
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.shared.message import ServerMessageMetadata
from mcp.shared.transport_context import TransportContext
from tests.interaction._connect import (
    base_headers,
    connect_over_streamable_http,
    initialize_body,
    initialize_via_http,
    mounted_app,
    parse_sse_messages,
)
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
        if stream_id.endswith(":request:42") and message is not None:
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

    assert transport._streams == {}  # pyright: ignore[reportPrivateUsage]
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


async def test_an_event_store_failure_costs_that_request_its_resumability_only() -> None:
    """A store that raises for a request's stream still lets the answer through live.

    Request 42 cannot be stored, so its result reaches the client unstored (no event id to
    resume from) and the store's error text never touches the wire; request 43 on the same
    session is stored and served normally.
    """

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        return CallToolResult(content=[TextContent(text=params.name)])

    server = Server("resilient", on_call_tool=call_tool)
    store = _StreamFailingStore()

    async with mounted_app(server, event_store=store, retry_interval=0) as (http, _):
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

    # Request 42's answer went out live (the store never took it) and no backend text leaked.
    stored_ids = {message.id for _, message in store._events if isinstance(message, JSONRPCResponse)}  # pyright: ignore[reportPrivateUsage]
    assert 42 not in stored_ids and 43 in stored_ids
    (first,) = [message for message in parse_sse_messages(failing_events) if isinstance(message, JSONRPCResponse)]
    assert first.id == 42
    assert first.result["content"] == [{"type": "text", "text": "first"}]
    assert all("fell over" not in (event.data or "") for event in failing_events)
    # Request 43 was stored and delivered as usual.
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
    assert stale_reader is not None
    channel.detach()  # e.g. close_sse_stream()
    fresh_reader = channel.attach()  # the client's reconnect re-attached
    assert fresh_reader is not None
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
    reader = channel.attach()
    assert reader is not None

    dctx.close()

    await dctx.notify("notifications/message", {"level": "info", "data": "too late"})
    with pytest.raises(anyio.WouldBlock):
        reader.receive_nowait()  # nothing reached the response stream
    reader.close()
    channel.close()
    with pytest.raises(NoBackChannelError):
        await dctx.send_raw_request("ping", None)


class _SlowFirstStore(EventStore):
    """The first `store_event` call is slow, so an unordered second writer could overtake it."""

    def __init__(self) -> None:
        self.count = 0

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        self.count += 1
        event_id = str(self.count)
        if event_id == "1":
            for _ in range(5):
                await anyio.lowlevel.checkpoint()
        return event_id

    async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
        raise NotImplementedError


async def test_concurrent_writes_reach_the_wire_in_event_store_order() -> None:
    """Two tasks writing one channel are delivered in the order the event store recorded them.

    A `Last-Event-ID` resume replays in store order, so the wire must never diverge from it.
    """
    channel = _MessageChannel("1", _SlowFirstStore())
    reader = channel.attach()
    assert reader is not None
    first = JSONRPCNotification(jsonrpc="2.0", method="notifications/one")
    second = JSONRPCNotification(jsonrpc="2.0", method="notifications/two")

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(channel.write, first)
            await anyio.lowlevel.checkpoint()  # let the first writer reach the store
            tg.start_soon(channel.write, second)

    delivered = [reader.receive_nowait(), reader.receive_nowait()]
    reader.close()
    channel.close()
    assert [(event.event_id, event.message) for event in delivered] == [("1", first), ("2", second)]


class _GatedPrimingStore(SequencedEventStore):
    """Parks request ``42``'s priming write until released, so a DELETE can land mid-request."""

    def __init__(self) -> None:
        super().__init__()
        self.parked = anyio.Event()
        self.release = anyio.Event()

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        if stream_id.endswith(":request:42") and message is None:
            self.parked.set()
            await self.release.wait()
        return await super().store_event(stream_id, message)


async def test_a_request_arriving_across_termination_is_refused_not_run() -> None:
    """A POST suspended when its session is DELETEd is answered 404 rather than run on the dead session."""

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        raise NotImplementedError  # the handler must never run

    server = Server("terminating", on_call_tool=call_tool)
    store = _GatedPrimingStore()

    pending: list[int] = []
    async with mounted_app(server, event_store=store, retry_interval=0) as (http, _):
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch

                async def call() -> None:
                    response = await http.post(
                        "/mcp", content=_tools_call(42, "wait", {}), headers=base_headers(session_id=session_id)
                    )
                    pending.append(response.status_code)

                tg.start_soon(call)
                await store.parked.wait()
                delete = await http.delete("/mcp", headers=base_headers(session_id=session_id))
                assert delete.status_code == 200
                store.release.set()

    assert pending == [404]


class _BrokenReplayStore(SequencedEventStore):
    async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
        raise RuntimeError("replay backend unavailable")


async def test_a_failing_replay_ends_that_stream_and_the_session_keeps_working() -> None:
    """`replay_events_after` raising costs the reconnecting GET an empty stream, nothing more."""
    server = Server("replay-broken")

    async with mounted_app(server, event_store=_BrokenReplayStore(), retry_interval=0) as (http, _):
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            async with http.stream(  # pragma: no branch
                "GET", "/mcp", headers=base_headers(session_id=session_id) | {"last-event-id": "1"}
            ) as replay:
                assert replay.status_code == 200
                assert [event async for event in EventSource(replay)] == []
            ping = await http.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
                headers=base_headers(session_id=session_id),
            )
    assert ping.status_code == 200


async def test_json_mode_refuses_a_request_scoped_server_to_client_request() -> None:
    """In JSON-response mode an elicitation from a handler fails with a JSON-RPC error, not a hang.

    The POST's single JSON body has no stream to carry the nested request, so the transport
    raises `NoBackChannelError` (an `MCPError`) rather than waiting for an answer that could
    never be delivered.
    """

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        await ctx.session.send_request(
            ElicitRequest(
                params=ElicitRequestFormParams(message="ok?", requested_schema={"type": "object", "properties": {}})
            ),
            ElicitResult,
            metadata=ServerMessageMetadata(related_request_id=ctx.request_id),
        )
        raise NotImplementedError  # the request must be refused before reaching here

    server = Server("json-mode", on_call_tool=call_tool)

    async with connect_over_streamable_http(server, json_response=True) as client:
        with pytest.raises(MCPError) as exc_info, anyio.fail_after(5):
            await client.call_tool("ask", {})

    assert exc_info.value.error.code == INVALID_REQUEST


async def test_a_session_bound_transport_drops_notifications_once_its_session_has_ended() -> None:
    """A POSTed notification landing after the session task is gone is dropped, not handled."""
    transport = StreamableHTTPServerTransport("sid", app=Server("ended"), lifespan_state={})
    # The session task (`run()`) never started, so the transport has no live session to hand work to.
    request = MagicMock(spec=Request)
    request.headers = {}

    with anyio.fail_after(5):
        await transport._deliver_client_message(  # pyright: ignore[reportPrivateUsage]
            request, JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")
        )


async def test_requests_wait_for_a_handshake_in_progress_to_commit() -> None:
    """A request POSTed while `initialize` is still running is held until the handshake commits.

    The session id ships with the initialize response's headers, ahead of its result, so a
    client can send its next request before the server committed the negotiated session state.
    The transport orders that request behind the handshake, so it is served against the
    initialized session rather than racing the initialization gate.
    """
    release_handshake = anyio.Event()

    class _SlowHandshake:
        async def __call__(self, ctx: ServerRequestContext, call_next: CallNext) -> HandlerResult:
            if ctx.method == "initialize":
                await release_handshake.wait()
            return await call_next(ctx)

    server = Server("gated")
    server.middleware.append(_SlowHandshake())
    listed: list[int] = []

    async with mounted_app(server) as (http, _):
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch
                async with http.stream(  # pragma: no branch
                    "POST", "/mcp", json=initialize_body(), headers=base_headers()
                ) as init:
                    # The session id arrives with the headers, before the handshake finishes.
                    session_id = init.headers["mcp-session-id"]

                    async def list_tools() -> None:
                        response = await http.post(
                            "/mcp",
                            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                            headers=base_headers(session_id=session_id),
                        )
                        listed.append(response.status_code)

                    tg.start_soon(list_tools)
                    await anyio.wait_all_tasks_blocked()
                    assert listed == []  # held behind the still-running handshake
                    release_handshake.set()
                    [event async for event in EventSource(init)]

    assert listed == [200]


async def test_a_server_request_no_client_can_receive_fails_the_call_instead_of_hanging() -> None:
    """A server-to-client request with nothing to carry it fails the handler right away.

    With no GET stream attached and no event store there is nowhere a connection-scoped
    request could ever reach the client, so the call is failed `CONNECTION_CLOSED` instead
    of parking the handler for an answer that cannot arrive.
    """
    outcomes: list[int] = []

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        try:
            # No `related_request_id`: this rides the connection's standalone GET stream.
            await ctx.session.send_request(
                ElicitRequest(
                    params=ElicitRequestFormParams(message="ok?", requested_schema={"type": "object", "properties": {}})
                ),
                ElicitResult,
            )
        except MCPError as exc:
            outcomes.append(exc.error.code)
            raise
        raise NotImplementedError

    server = Server("no-back-channel", on_call_tool=call_tool)

    async with mounted_app(server) as (http, _):  # no event store, and no GET stream is ever opened
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            async with http.stream(  # pragma: no branch
                "POST", "/mcp", content=_tools_call(2, "ask", {}), headers=base_headers(session_id=session_id)
            ) as response:
                assert response.status_code == 200
                events = [event async for event in EventSource(response)]

    assert outcomes == [CONNECTION_CLOSED]
    # The tool's failure came back on its own stream as an error frame.
    (error,) = [message for message in parse_sse_messages(events) if isinstance(message, JSONRPCError)]
    assert error.id == 2


class _StandaloneFlakyStore(SequencedEventStore):
    """The store rejects the first message written to the standalone stream, then recovers."""

    def __init__(self) -> None:
        super().__init__()
        self.failed_once = False

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        if stream_id.endswith(":_GET_stream") and message is not None and not self.failed_once:
            self.failed_once = True
            raise RuntimeError("standalone backend hiccup")
        return await super().store_event(stream_id, message)


async def test_a_store_failure_on_the_standalone_stream_does_not_take_the_stream_down() -> None:
    """A store that raises for a standalone notification degrades that message, not the GET stream.

    The failed notification still reaches the connected client live (unstored); the next one
    is stored and delivered too - the stream stays alive across the store's hiccup.
    """

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        await ctx.session.send_resource_updated("file:///one")
        await ctx.session.send_resource_updated("file:///two")
        return CallToolResult(content=[])

    server = Server("standalone-flaky", on_call_tool=call_tool)
    store = _StandaloneFlakyStore()

    async with mounted_app(server, event_store=store, retry_interval=0) as (http, _):
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            async with http.stream(  # pragma: no branch
                "GET", "/mcp", headers=base_headers(session_id=session_id)
            ) as sse:
                assert sse.status_code == 200
                events = aiter(EventSource(sse))
                called = await http.post(
                    "/mcp", content=_tools_call(2, "log", {}), headers=base_headers(session_id=session_id)
                )
                assert called.status_code == 200
                updated = [
                    JSONRPCNotification.model_validate_json((await anext(events)).data or "{}") for _ in range(2)
                ]

    assert [n.params and n.params["uri"] for n in updated] == ["file:///one", "file:///two"]
    assert store.failed_once


async def test_a_shared_event_store_keeps_sessions_replay_apart() -> None:
    """Two sessions on one store never see each other's frames on a `Last-Event-ID` resume.

    Both sessions run the same request ids, so a store keyed on the bare request id would
    interleave them; session-scoped stream ids keep session B's replay to its own messages.
    """

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.arguments is not None
        return CallToolResult(content=[TextContent(text=str(params.arguments["owner"]))])

    server = Server("shared-store", on_call_tool=call_tool)
    store = SequencedEventStore()

    async with mounted_app(server, event_store=store, retry_interval=0) as (http, _):
        with anyio.fail_after(5):
            session_a = await initialize_via_http(http)
            session_b = await initialize_via_http(http)
            events_by_session: dict[str, list[Any]] = {}
            for session_id, owner in ((session_a, "A"), (session_b, "B")):
                async with http.stream(
                    "POST",
                    "/mcp",
                    content=_tools_call(3, "who", {"owner": owner}),
                    headers=base_headers(session_id=session_id),
                ) as response:
                    events_by_session[session_id] = [event async for event in EventSource(response)]
            # Resume session B's request-3 stream from its priming event: only B's frames come back.
            priming_a = [event.id for event in events_by_session[session_a] if event.id][0]
            priming_b = [event.id for event in events_by_session[session_b] if event.id][0]
            async with http.stream(  # pragma: no branch
                "GET",
                "/mcp",
                headers=base_headers(session_id=session_b) | {"last-event-id": priming_b},
            ) as replay:
                replayed = [event async for event in EventSource(replay)]
            # ... while an event id belonging to session A yields B nothing.
            async with http.stream(  # pragma: no branch
                "GET",
                "/mcp",
                headers=base_headers(session_id=session_b) | {"last-event-id": priming_a},
            ) as poached:
                foreign = [event async for event in EventSource(poached)]

    payloads = [message for message in parse_sse_messages(replayed) if isinstance(message, JSONRPCResponse)]
    assert [message.result["content"][0]["text"] for message in payloads] == ["B"]
    # Presenting session A's event id from session B replays nothing at all.
    assert [message for message in parse_sse_messages(foreign) if isinstance(message, JSONRPCResponse)] == []


async def test_a_request_id_shaped_like_the_get_marker_keeps_its_own_stream() -> None:
    """A request whose id is the string `_GET_stream` is served on its own stream.

    Its response never lands on the standalone GET stream, and the standalone stream stays
    attached across it.
    """
    server = Server("marker-id")

    async with mounted_app(server) as (http, manager):
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            async with http.stream(  # pragma: no branch
                "GET", "/mcp", headers=base_headers(session_id=session_id)
            ) as standalone:
                assert standalone.status_code == 200
                async with http.stream(  # pragma: no branch
                    "POST",
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": "_GET_stream", "method": "ping"},
                    headers=base_headers(session_id=session_id),
                ) as pinged:
                    assert pinged.status_code == 200
                    (response,) = parse_sse_messages([event async for event in EventSource(pinged)])
                assert isinstance(response, JSONRPCResponse) and response.id == "_GET_stream"
                # The standalone stream is still attached; the ping never touched it.
                transport = manager._server_instances[session_id]  # pyright: ignore[reportPrivateUsage]
                assert transport._standalone.attached  # pyright: ignore[reportPrivateUsage]


async def test_a_json_mode_request_terminated_underneath_it_is_answered_404() -> None:
    """DELETE while a JSON-mode request runs leaves it no answer, so the POST gets the terminated 404."""
    started = anyio.Event()

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        started.set()
        await anyio.sleep_forever()
        raise NotImplementedError

    server = Server("json-terminate", on_call_tool=call_tool)
    statuses: list[int] = []

    async with mounted_app(server, json_response=True) as (http, _):
        with anyio.fail_after(5):
            # JSON mode answers `initialize` with a plain JSON body.
            initialized = await http.post("/mcp", json=initialize_body(), headers=base_headers())
            assert initialized.status_code == 200
            session_id = initialized.headers["mcp-session-id"]
            async with anyio.create_task_group() as tg:  # pragma: no branch

                async def call() -> None:
                    response = await http.post(
                        "/mcp", content=_tools_call(2, "wait", {}), headers=base_headers(session_id=session_id)
                    )
                    statuses.append(response.status_code)

                tg.start_soon(call)
                await started.wait()
                delete = await http.delete("/mcp", headers=base_headers(session_id=session_id))
                assert delete.status_code == 200

    assert statuses == [404]


class _GatedReplayStore(SequencedEventStore):
    """Parks `replay_events_after` until released, so a DELETE can land mid-replay."""

    def __init__(self) -> None:
        super().__init__()
        self.parked = anyio.Event()
        self.release = anyio.Event()

    async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
        self.parked.set()
        await self.release.wait()
        return await super().replay_events_after(last_event_id, send_callback)


async def test_a_replay_across_termination_ends_instead_of_tailing_a_dead_stream() -> None:
    """DELETE while a standalone-stream replay reads the store ends that response cleanly.

    The resumed GET finds its stream gone once the store read returns, so it closes with no
    live tail rather than attaching to a terminated channel.
    """

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        await ctx.session.send_resource_updated("file:///seed")
        return CallToolResult(content=[])

    server = Server("replay-terminate", on_call_tool=call_tool)
    store = _GatedReplayStore()
    replayed: list[list[Any]] = []

    async with mounted_app(server, event_store=store, retry_interval=0) as (http, manager):
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            # Seed the standalone stream with one stored event, and note its id.
            async with http.stream("GET", "/mcp", headers=base_headers(session_id=session_id)) as sse:
                events = aiter(EventSource(sse))
                seeded = await http.post(
                    "/mcp", content=_tools_call(2, "seed", {}), headers=base_headers(session_id=session_id)
                )
                assert seeded.status_code == 200
                last_event_id = (await anext(events)).id
            assert last_event_id is not None
            transport = manager._server_instances[session_id]  # pyright: ignore[reportPrivateUsage]
            while transport._standalone.attached:  # pyright: ignore[reportPrivateUsage]
                await anyio.wait_all_tasks_blocked()  # let the closed GET detach

            async with anyio.create_task_group() as tg:  # pragma: no branch

                async def replay() -> None:
                    async with http.stream(
                        "GET",
                        "/mcp",
                        headers=base_headers(session_id=session_id) | {"last-event-id": last_event_id},
                    ) as response:
                        replayed.append([event async for event in EventSource(response)])

                tg.start_soon(replay)
                await store.parked.wait()
                delete = await http.delete("/mcp", headers=base_headers(session_id=session_id))
                assert delete.status_code == 200
                store.release.set()

    (events,) = replayed
    assert [event for event in events if event.data] == []


async def test_overlapping_handshakes_each_release_their_own_gate() -> None:
    """A second `initialize` POSTed while the first runs installs its own gate; both are answered.

    Whichever handshake finishes clears only its own gate, so neither leaves a stale gate
    holding later requests forever.
    """
    release_handshake = anyio.Event()

    class _SlowHandshake:
        async def __call__(self, ctx: ServerRequestContext, call_next: CallNext) -> HandlerResult:
            if ctx.method == "initialize" and ctx.request_id != 1:  # let the session's first one through
                await release_handshake.wait()
            return await call_next(ctx)

    server = Server("regated")
    server.middleware.append(_SlowHandshake())
    statuses: list[int] = []

    async def handshake(http: Any, session_id: str, request_id: int) -> None:
        response = await http.post(
            "/mcp", json=initialize_body(request_id), headers=base_headers(session_id=session_id)
        )
        statuses.append(response.status_code)

    async with mounted_app(server, json_response=True) as (http, _):
        with anyio.fail_after(5):
            first = await http.post("/mcp", json=initialize_body(), headers=base_headers())
            session_id = first.headers["mcp-session-id"]
            async with anyio.create_task_group() as tg:  # pragma: no branch
                tg.start_soon(handshake, http, session_id, 2)
                await anyio.wait_all_tasks_blocked()
                tg.start_soon(handshake, http, session_id, 3)
                await anyio.wait_all_tasks_blocked()
                release_handshake.set()
            listed = await http.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
                headers=base_headers(session_id=session_id),
            )

    assert statuses == [200, 200]
    assert listed.status_code == 200
