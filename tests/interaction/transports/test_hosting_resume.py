"""Resumability over the streamable HTTP transport, exercised entirely in process.

These tests configure the server with an event store, so every SSE event is stamped with an ID
and a client that loses its connection can resume by sending `Last-Event-ID`. The wire-level
tests (`mounted_app` + raw httpx) assert exactly what travels on the wire; the end-to-end test
drives the SDK client through a server-initiated stream close and proves the call still
completes. The bridge's `aclose()` delivers `http.disconnect` to the running application, so
closing a streaming response mid-read is a deterministic in-process disconnect -- no sockets,
no real time. Every server here uses `retry_interval=0` so reconnection waits are no-ops.
"""

import json

import anyio
import httpx
import pytest
from httpx_sse import EventSource, ServerSentEvent
from inline_snapshot import snapshot
from mcp_types import (
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    LoggingMessageNotificationParams,
    TextContent,
    jsonrpc_message_adapter,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.message import ClientMessageMetadata
from tests.interaction._connect import (
    BASE_URL,
    base_headers,
    connect_over_streamable_http,
    initialize_via_http,
    mounted_app,
    parse_sse_messages,
)
from tests.interaction._requirements import requirement
from tests.interaction.transports._event_store import SequencedEventStore

pytestmark = pytest.mark.anyio


def _counting_server() -> MCPServer:
    """A server with one tool that emits related notifications and one unrelated notification."""
    mcp = MCPServer("resumable")

    @mcp.tool()
    async def count(ctx: Context, n: int) -> str:
        """Emit n log notifications related to this call, plus one unrelated resource update."""
        for i in range(1, n + 1):
            await ctx.info(f"tick {i}")  # pyright: ignore[reportDeprecated]
        await ctx.session.send_resource_updated("file:///elsewhere.txt")
        return f"counted to {n}"

    return mcp


def _tools_call(request_id: int, name: str, arguments: dict[str, object]) -> str:
    """A serialized tools/call JSON-RPC request body."""
    return JSONRPCRequest(
        jsonrpc="2.0", id=request_id, method="tools/call", params={"name": name, "arguments": arguments}
    ).model_dump_json(by_alias=True, exclude_none=True)


async def _read_events(response: httpx.Response, count: int) -> list[ServerSentEvent]:
    """Read exactly `count` SSE events from a streaming response without closing it."""
    source = EventSource(response).aiter_sse()
    return [await anext(source) for _ in range(count)]


@requirement("hosting:resume:event-ids")
@requirement("hosting:resume:priming")
async def test_a_post_sse_stream_begins_with_a_priming_event_and_stamps_every_event() -> None:
    """A request's SSE stream opens with a priming event (id, empty data, retry) then stamps each message."""
    async with mounted_app(_counting_server(), event_store=SequencedEventStore(), retry_interval=0) as (http, _):
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            async with http.stream(  # pragma: no branch
                "POST", "/mcp", content=_tools_call(1, "count", {"n": 2}), headers=base_headers(session_id=session_id)
            ) as response:
                assert response.status_code == 200
                events = await _read_events(response, 4)

    priming, first, second, result = events
    # The priming event is the only event a client could have seen before any work happened, so it
    # is the resumption anchor: it carries an ID and empty data. The SDK attaches the retry hint
    # to this event (see the divergence on hosting:resume:priming).
    assert (priming.id, priming.data, priming.retry) == snapshot(("3", "", 0))
    assert priming.event == snapshot("message")
    # Every subsequent event carries an event-store ID; the related notifications and the response
    # all ride this stream and close it after the response.
    assert [event.id for event in (first, second, result)] == snapshot(["4", "5", "7"])
    assert [json.loads(event.data)["method"] for event in (first, second)] == snapshot(
        ["notifications/message", "notifications/message"]
    )
    assert jsonrpc_message_adapter.validate_json(result.data) == snapshot(
        JSONRPCResponse(
            jsonrpc="2.0",
            id=1,
            result={
                "content": [{"type": "text", "text": "counted to 2"}],
                "structuredContent": {"result": "counted to 2"},
                "isError": False,
            },
        )
    )


@requirement("hosting:resume:priming")
async def test_the_priming_row_is_stored_before_any_handler_output_for_that_stream() -> None:
    """The priming cursor is the first row the event store records for a request's stream.

    The POST handler stores the priming row before dispatching the request, so by construction
    it precedes anything `message_router` can store for that stream id.
    """
    store = SequencedEventStore()
    mcp = MCPServer("resumable")

    @mcp.tool()
    async def burst(ctx: Context) -> str:
        await ctx.info("a")  # pyright: ignore[reportDeprecated]
        await ctx.info("b")  # pyright: ignore[reportDeprecated]
        await ctx.info("c")  # pyright: ignore[reportDeprecated]
        return "done"

    async with mounted_app(mcp, event_store=store) as (http, _):
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            async with http.stream(  # pragma: no branch
                "POST", "/mcp", content=_tools_call(2, "burst", {}), headers=base_headers(session_id=session_id)
            ) as response:
                await _read_events(response, 5)

    # initialize wrote two rows (its own priming + response); everything after is this call.
    call_rows = store._events[2:]
    stream_id = call_rows[0][0]
    assert [(s, None if m is None else type(m).__name__) for s, m in call_rows] == [
        (stream_id, None),
        (stream_id, "JSONRPCNotification"),
        (stream_id, "JSONRPCNotification"),
        (stream_id, "JSONRPCNotification"),
        (stream_id, "JSONRPCResponse"),
    ]


@requirement("hosting:resume:replay")
@requirement("hosting:resume:stream-scoped")
@requirement("hosting:resume:buffered-replay")
async def test_get_with_last_event_id_replays_only_that_streams_missed_events() -> None:
    """Reconnecting with Last-Event-ID returns the missed events from that one stream, in order.

    The handler also emits an unrelated notification (which the server stores under the
    standalone-stream key); replay must not return it, proving replay is scoped to the stream
    the given event ID belongs to.

    Steps: (1) initialize; (2) POST a tool call and read events until the first notification is
    captured; (3) close the response mid-stream -- the bridge delivers `http.disconnect`, the
    handler keeps running; (4) release the handler so it emits the remaining messages, which the
    server buffers in the event store; (5) wait on the event store for the handler's response to
    be stored, so the replay's content is independent of task scheduling; (6) GET with
    `Last-Event-ID` and assert the replay is exactly the missed events from this request's stream.
    """
    release = anyio.Event()
    store = SequencedEventStore()

    mcp = MCPServer("resumable")

    @mcp.tool()
    async def count(ctx: Context) -> str:
        """Emit one related notification, wait for the test, then emit two more plus an unrelated one."""
        await ctx.info("tick 1")  # pyright: ignore[reportDeprecated]
        await release.wait()
        await ctx.info("tick 2")  # pyright: ignore[reportDeprecated]
        await ctx.info("tick 3")  # pyright: ignore[reportDeprecated]
        await ctx.session.send_resource_updated("file:///elsewhere.txt")
        return "counted"

    async with mounted_app(mcp, event_store=store, retry_interval=0) as (http, _):
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            async with http.stream(
                "POST", "/mcp", content=_tools_call(1, "count", {}), headers=base_headers(session_id=session_id)
            ) as response:
                # Read the priming event and the first notification, then drop the connection.
                priming, first = await _read_events(response, 2)
                assert (priming.id, first.id) == snapshot(("3", "4"))
                last_seen = first.id
            release.set()
            # The handler keeps running after the disconnect; its remaining messages are stored.
            # The first wait returns immediately (the priming and first tick are already stored);
            # the second blocks until the response itself is stored so the replay content is fixed.
            await store.wait_until_stored(4)
            await store.wait_until_stored(8)
            replay_headers = base_headers(session_id=session_id) | {"last-event-id": last_seen}
            async with http.stream("GET", "/mcp", headers=replay_headers) as replay:  # pragma: no branch
                assert replay.status_code == 200
                missed = await _read_events(replay, 3)

    decoded = parse_sse_messages(missed)
    # Exactly the two remaining related notifications and the response, with their original IDs.
    assert [event.id for event in missed] == snapshot(["5", "6", "8"])
    assert [type(message).__name__ for message in decoded] == snapshot(
        ["JSONRPCNotification", "JSONRPCNotification", "JSONRPCResponse"]
    )
    assert isinstance(decoded[2], JSONRPCResponse)
    assert decoded[2].id == 1
    # The unrelated resource-updated notification was stored under the standalone-stream key, not
    # this request's stream, so it must not appear in the replay.
    assert all(
        not (isinstance(message, JSONRPCNotification) and message.method == "notifications/resources/updated")
        for message in decoded
    )


@requirement("hosting:resume:priming")
async def test_a_pre_2025_11_25_reconnect_replays_without_minting_a_priming_event() -> None:
    """A pre-2025-11-25 client reconnecting via Last-Event-ID gets the replay with no priming row.

    The store-length assertion is the load-bearing proof that no priming cursor was minted.
    """
    release = anyio.Event()
    store = SequencedEventStore()
    mcp = MCPServer("resumable")

    @mcp.tool()
    async def count(ctx: Context) -> str:
        await ctx.info("tick 1")  # pyright: ignore[reportDeprecated]
        await release.wait()
        await ctx.info("tick 2")  # pyright: ignore[reportDeprecated]
        return "counted"

    async with mounted_app(mcp, event_store=store, retry_interval=0) as (http, _):
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            async with http.stream(
                "POST", "/mcp", content=_tools_call(1, "count", {}), headers=base_headers(session_id=session_id)
            ) as response:
                _, first = await _read_events(response, 2)
            release.set()
            await store.wait_until_stored(6)
            old_client_headers = base_headers(session_id=session_id) | {
                "mcp-protocol-version": "2025-06-18",
                "last-event-id": first.id,
            }
            async with http.stream("GET", "/mcp", headers=old_client_headers) as replay:  # pragma: no branch
                assert replay.status_code == 200
                missed = await _read_events(replay, 2)

    assert [(event.id, bool(event.data)) for event in missed] == snapshot([("5", True), ("6", True)])
    # No priming cursor was minted on reconnect: the store still holds only the six rows
    # written before the GET (init priming+response, POST priming, tick 1, tick 2, result).
    assert len(store._events) == 6


@requirement("hosting:resume:bad-event-id")
async def test_an_unknown_last_event_id_yields_an_empty_replay_stream() -> None:
    """A Last-Event-ID the event store cannot map produces an empty SSE stream rather than an error.

    See the divergence on hosting:resume:bad-event-id: this pins current behaviour.
    """
    async with mounted_app(_counting_server(), event_store=SequencedEventStore(), retry_interval=0) as (http, _):
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            for unknown in ("no-such-event", "0"):
                headers = base_headers(session_id=session_id) | {"last-event-id": unknown}
                async with http.stream("GET", "/mcp", headers=headers) as replay:
                    assert replay.status_code == 200
                    assert replay.headers["content-type"].startswith("text/event-stream")
                    events = [event async for event in EventSource(replay).aiter_sse()]
                assert events == []


@requirement("hosting:http:disconnect-not-cancel")
async def test_dropping_the_connection_mid_request_does_not_cancel_the_handler() -> None:
    """Closing the request's SSE connection while the handler is running leaves the handler running.

    The handler signals when it has started and when it has finished; the test drops the
    connection in between and then releases the handler. If the disconnect cancelled the handler,
    `finished` would never be set and the test would time out.
    """
    started = anyio.Event()
    release = anyio.Event()
    finished = anyio.Event()

    mcp = MCPServer("resumable")

    @mcp.tool()
    async def hold(ctx: Context) -> str:
        """Signal start, wait for the test, signal completion."""
        started.set()
        await release.wait()
        await ctx.info("released")  # pyright: ignore[reportDeprecated]
        finished.set()
        return "held"

    async with mounted_app(mcp, event_store=SequencedEventStore(), retry_interval=0) as (http, _):
        session_id = await initialize_via_http(http)
        with anyio.fail_after(5):
            async with http.stream(
                "POST", "/mcp", content=_tools_call(1, "hold", {}), headers=base_headers(session_id=session_id)
            ) as response:
                await _read_events(response, 1)
                await started.wait()
            assert not finished.is_set()
            release.set()
            await finished.wait()


# This test intentionally carries every automatic-reconnection requirement: the
# close-then-resume scenario is indivisible, so splitting it would mean five near-identical bodies.
@requirement("hosting:resume:close-stream")
@requirement("transport:streamable-http:resumability")
@requirement("client-transport:http:reconnect-post-priming")
@requirement("client-transport:http:reconnect-retry-value")
@requirement("flow:resume:tool-call-resumption-token")
async def test_a_call_whose_stream_the_server_closes_is_resumed_by_the_client() -> None:
    """A server-closed request stream is reconnected by the client and the call completes.

    The handler emits one notification, closes its own SSE stream, then (once released) emits
    another and returns. The client observed the priming event (so it has a Last-Event-ID and a
    retry hint of 0ms), sees the stream end, reconnects via GET with Last-Event-ID, and receives
    the post-close notification and the result over the replay stream. The shared events make the
    test deterministic: the handler only proceeds once the test knows the first notification has
    arrived (and so the client's reconnection has begun).
    """
    received: list[object] = []
    before_seen = anyio.Event()
    gate = anyio.Event()
    done = anyio.Event()

    mcp = MCPServer("resumable")

    @mcp.tool()
    async def interrupt(ctx: Context) -> str:
        """Emit, close this call's SSE stream, then emit again after the test releases the gate."""
        await ctx.info("before close")  # pyright: ignore[reportDeprecated]
        await ctx.close_sse_stream()
        await gate.wait()
        await ctx.info("after close")  # pyright: ignore[reportDeprecated]
        done.set()
        return "resumed"

    async def collect(params: LoggingMessageNotificationParams) -> None:
        received.append(params.data)
        if params.data == "before close":
            before_seen.set()

    result: list[CallToolResult] = []
    async with connect_over_streamable_http(
        mcp, event_store=SequencedEventStore(), retry_interval=0, logging_callback=collect
    ) as client:
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch

                async def call() -> None:
                    result.append(await client.call_tool("interrupt", {}))

                tg.start_soon(call)
                await before_seen.wait()
                gate.set()
                await done.wait()

    assert result == snapshot(
        [CallToolResult(content=[TextContent(text="resumed")], structured_content={"result": "resumed"})]
    )
    assert received == snapshot(["before close", "after close"])


@requirement("hosting:resume:close-stream")
@requirement("transport:streamable-http:resumability")
@requirement("client-transport:http:reconnect-post-priming")
@requirement("client-transport:http:reconnect-retry-value")
async def test_a_call_whose_stream_closes_and_cannot_be_resumed_fails_instead_of_hanging() -> None:
    """If a resumable response stream disconnects and the server session is gone, the client fails
    the request instead of hanging forever.

    The server closes the call's SSE stream after emitting one related notification. The test then
    deletes the active server-side session to force the client's reconnect GET to return 404.
    Without a terminal response/error on the read stream, ClientSession.send_request waits forever
    (read timeout defaults to None). The transport must surface a request-scoped error when it
    gives up reconnecting.
    """
    reconnect_attempted = anyio.Event()
    allow_exit = anyio.Event()
    done = anyio.Event()
    raised: list[BaseException] = []
    manager_ref = None
    deleted_session = False

    mcp = MCPServer("resumable")

    @mcp.tool()
    async def interrupt(ctx: Context) -> str:
        await ctx.info("before close")  # pyright: ignore[reportDeprecated]
        await ctx.close_sse_stream()
        await allow_exit.wait()
        return "unreachable"

    async def record_request(request: httpx.Request) -> None:
        nonlocal deleted_session
        if request.method != "GET":
            return
        if request.headers.get("last-event-id") is None:
            return
        reconnect_attempted.set()
        if deleted_session or manager_ref is None:
            return
        session_ids = list(manager_ref._server_instances.keys())
        if session_ids:  # pragma: no branch
            del manager_ref._server_instances[session_ids[0]]
            deleted_session = True

    async with mounted_app(mcp, event_store=SequencedEventStore(), retry_interval=0, on_request=record_request) as (
        http,
        manager,
    ):
        manager_ref = manager
        with anyio.fail_after(5):  # pragma: no branch
            async with (  # pragma: no branch
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http, terminate_on_close=False) as (r, w),
                ClientSession(r, w) as session,
                anyio.create_task_group() as tg,
            ):
                await session.initialize()

                async def call() -> None:
                    try:
                        await session.call_tool("interrupt", {})
                    except BaseException as exc:
                        raised.append(exc)
                    finally:
                        done.set()

                tg.start_soon(call)
                await reconnect_attempted.wait()
                await done.wait()
                allow_exit.set()
                tg.cancel_scope.cancel()

    assert len(raised) == 1
    assert isinstance(raised[0], Exception)
    assert "reconnection attempts were exhausted" in str(raised[0]).lower()


@requirement("client-transport:http:resume-stream-api")
async def test_a_captured_resumption_token_replays_missed_messages_on_a_new_connection() -> None:
    """A resumption token captured via on_resumption_token_update on one connection lets a fresh
    connection retrieve the messages it missed by passing resumption_token to send_request.

    This is the explicit ClientMessageMetadata API, distinct from the automatic reconnection the
    previous test covers: the transport dispatches a resumption_token request as a GET with
    Last-Event-ID instead of POSTing the body, and remaps the replayed response onto the new
    request's id. Client.call_tool does not expose ClientMessageMetadata, so the test drives a
    bare ClientSession via session.send_request -- the sanctioned drop-down for behaviour Client
    cannot express. The second connection carries the original session id but does not initialize
    (the server-side session already is), modelling a caller that resumes after a process restart.
    """
    captured: list[str] = []
    received: list[object] = []
    first_seen = anyio.Event()
    token_seen = anyio.Event()
    release = anyio.Event()
    store = SequencedEventStore()

    mcp = MCPServer("resumable")

    @mcp.tool()
    async def hold(ctx: Context) -> str:
        """Emit one notification, wait for the test, emit another, return."""
        await ctx.info("first")  # pyright: ignore[reportDeprecated]
        await release.wait()
        await ctx.info("second")  # pyright: ignore[reportDeprecated]
        return "done"

    async def on_token(token: str) -> None:
        captured.append(token)
        if len(captured) >= 2:
            token_seen.set()

    async def collect(params: LoggingMessageNotificationParams) -> None:
        received.append(params.data)
        first_seen.set()

    call = CallToolRequest(params=CallToolRequestParams(name="hold", arguments={}))
    capture = ClientMessageMetadata(on_resumption_token_update=on_token)

    async with mounted_app(mcp, event_store=store, retry_interval=0) as (http, manager):
        with anyio.fail_after(5):  # pragma: no branch
            async with (  # pragma: no branch
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http, terminate_on_close=False) as (r1, w1),
                ClientSession(r1, w1, logging_callback=collect) as first,
                anyio.create_task_group() as tg,
            ):
                await first.initialize()
                tg.start_soon(first.send_request, call, CallToolResult, None, capture)
                await first_seen.wait()
                await token_seen.wait()
                assert captured == snapshot(["3", "4"])
                assert received == snapshot(["first"])
                # The session id is only observable via the manager (the client transport does not expose it).
                (session_id,) = manager._server_instances
                http.headers["mcp-session-id"] = session_id
                http.headers["mcp-protocol-version"] = LATEST_HANDSHAKE_VERSION
                tg.cancel_scope.cancel()

        with anyio.fail_after(5):  # pragma: no branch
            release.set()  # pragma: lax no cover  — python/cpython#106749: 3.11 drops this line event
            # init priming + init response + call priming + "first" + "second" + result = 6 stored events.
            await store.wait_until_stored(6)
            async with (  # pragma: no branch
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http) as (r2, w2),
                ClientSession(r2, w2, logging_callback=collect) as second,
            ):
                result = await second.send_request(
                    call, CallToolResult, metadata=ClientMessageMetadata(resumption_token=captured[-1])
                )
    assert result == snapshot(CallToolResult(content=[TextContent(text="done")], structured_content={"result": "done"}))
    assert received == snapshot(["first", "second"])
