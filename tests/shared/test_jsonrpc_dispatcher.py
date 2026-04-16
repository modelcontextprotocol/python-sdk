"""JSON-RPC-specific Dispatcher tests.

Behaviors with no `DirectDispatcher` analog: request-id correlation, the
exception-to-wire boundary, peer-cancel handling, and shutdown fan-out.
The contract tests shared with `DirectDispatcher` live in
``test_dispatcher.py``.
"""

import contextvars
from collections.abc import Mapping
from typing import Any

import anyio
import pytest

from mcp.shared._context_streams import ContextReceiveStream, ContextSendStream
from mcp.shared.dispatcher import DispatchContext
from mcp.shared.exceptions import MCPError
from mcp.shared.jsonrpc_dispatcher import (  # pyright: ignore[reportPrivateUsage]
    JSONRPCDispatcher,
    _outbound_metadata,
    _Pending,
)
from mcp.shared.message import ClientMessageMetadata, ServerMessageMetadata, SessionMessage
from mcp.shared.transport_context import TransportContext
from mcp.types import (
    CONNECTION_CLOSED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    ErrorData,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    Tool,
)

from .conftest import jsonrpc_pair
from .test_dispatcher import Recorder, echo_handlers, running_pair

DCtx = DispatchContext[TransportContext]


@pytest.mark.anyio
async def test_concurrent_send_raw_requests_correlate_by_id_when_responses_arrive_out_of_order():
    release_first = anyio.Event()

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        if method == "first":
            await release_first.wait()
        return {"m": method}

    async with running_pair(jsonrpc_pair, server_on_request=server_on_request) as (client, *_):
        results: dict[str, dict[str, Any]] = {}

        async def call(method: str) -> None:
            results[method] = await client.send_raw_request(method, None)

        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch
                tg.start_soon(call, "first")
                await anyio.sleep(0)
                tg.start_soon(call, "second")
                await anyio.sleep(0)
                # second resolves while first is still parked
                assert "first" not in results
                release_first.set()
    assert results == {"first": {"m": "first"}, "second": {"m": "second"}}


@pytest.mark.anyio
async def test_handler_raising_exception_sends_internal_error_with_str_message():
    """Per design: INTERNAL_ERROR carries str(e), not a scrubbed message."""

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        raise RuntimeError("kaboom")

    async with running_pair(jsonrpc_pair, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", None)
    assert exc.value.error.code == INTERNAL_ERROR
    assert exc.value.error.message == "kaboom"
    assert exc.value.__cause__ is None  # cause does not survive the wire


@pytest.mark.anyio
async def test_peer_cancel_interrupt_mode_sets_cancel_requested_and_sends_no_response():
    handler_started = anyio.Event()
    handler_exited = anyio.Event()
    seen_ctx: list[DCtx] = []

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        seen_ctx.append(ctx)
        handler_started.set()
        try:
            await anyio.sleep_forever()
        finally:
            handler_exited.set()
        raise NotImplementedError

    async with running_pair(jsonrpc_pair, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch

                async def call_then_record() -> None:
                    with pytest.raises(MCPError):  # we'll cancel via tg below
                        await client.send_raw_request("slow", None)

                tg.start_soon(call_then_record)
                await handler_started.wait()
                # cancel just the handler (peer-cancel), not our caller
                await client.notify("notifications/cancelled", {"requestId": 1})
                await handler_exited.wait()
                # Handler torn down, no response was written; caller is still parked.
                # Cancel the caller's task to end the test.
                tg.cancel_scope.cancel()
    assert seen_ctx[0].cancel_requested.is_set()


@pytest.mark.anyio
async def test_peer_cancel_signal_mode_sets_event_but_handler_runs_to_completion():
    handler_started = anyio.Event()
    cancel_seen = anyio.Event()

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        handler_started.set()
        await ctx.cancel_requested.wait()
        cancel_seen.set()
        return {"finished": True}

    def factory(*, can_send_request: bool = True):
        client, server, close = jsonrpc_pair(can_send_request=can_send_request)
        # Reach in to set signal mode on the server side.
        assert isinstance(server, JSONRPCDispatcher)
        server._peer_cancel_mode = "signal"  # pyright: ignore[reportPrivateUsage]
        return client, server, close

    result_box: list[dict[str, Any]] = []
    async with running_pair(factory, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch

                async def call() -> None:
                    result_box.append(await client.send_raw_request("slow", None))

                tg.start_soon(call)
                await handler_started.wait()
                await client.notify("notifications/cancelled", {"requestId": 1})
                await cancel_seen.wait()
    assert result_box == [{"finished": True}]


@pytest.mark.anyio
async def test_send_raw_request_raises_connection_closed_when_read_stream_eofs_mid_await():
    """A blocked send_raw_request is woken with CONNECTION_CLOSED when run() exits."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)

            async def caller() -> None:
                with pytest.raises(MCPError) as exc:
                    await client.send_raw_request("ping", None)
                assert exc.value.error.code == CONNECTION_CLOSED

            tg.start_soon(caller)
            await anyio.sleep(0)
            # No server: simulate the peer dropping by closing the read side.
            s2c_send.close()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_late_response_after_timeout_is_dropped_without_crashing():
    handler_started = anyio.Event()
    proceed = anyio.Event()

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        handler_started.set()
        await proceed.wait()
        return {"late": True}

    async with running_pair(jsonrpc_pair, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            with pytest.raises(MCPError):  # REQUEST_TIMEOUT
                await client.send_raw_request("slow", None, {"timeout": 0})
            # The server handler is still running; let it finish and write a
            # response for an id the client has already discarded.
            await handler_started.wait()
            proceed.set()
            # One more round-trip proves the dispatcher is still healthy.
            assert await client.send_raw_request("ping", None) == {"late": True}


@pytest.mark.anyio
async def test_raise_handler_exceptions_true_propagates_out_of_run():
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)

    def builder(_rid: object, _meta: object) -> TransportContext:
        return TransportContext(kind="jsonrpc", can_send_request=True)

    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(
        c2s_recv, s2c_send, transport_builder=builder, raise_handler_exceptions=True
    )

    async def boom(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        raise RuntimeError("propagate me")

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    try:
        with pytest.raises(BaseException) as exc:
            async with anyio.create_task_group() as tg:
                await tg.start(server.run, boom, on_notify)
                # Inject a request directly onto the server's read stream.
                await c2s_send.send(
                    SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="x", params=None))
                )
        assert exc.group_contains(RuntimeError, match="propagate me")
        # The error response was still written before re-raising.
        sent = s2c_recv.receive_nowait()
        assert isinstance(sent, SessionMessage)
        assert isinstance(sent.message, JSONRPCError)
        assert sent.message.error.code == INTERNAL_ERROR
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_ctx_send_raw_request_tags_outbound_with_server_message_metadata():
    """Server-to-client requests carry related_request_id for SHTTP routing."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send)

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        return await ctx.send_raw_request("sampling/createMessage", {"prompt": "hi"})

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, server_on_request, on_notify)
            # Kick the server with an inbound request id=7.
            await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=7, method="t", params=None)))
            with anyio.fail_after(5):
                outbound = await s2c_recv.receive()
            assert isinstance(outbound, SessionMessage)
            assert isinstance(outbound.message, JSONRPCRequest)
            assert isinstance(outbound.metadata, ServerMessageMetadata)
            assert outbound.metadata.related_request_id == 7
            # Reply so the handler completes cleanly.
            await c2s_send.send(
                SessionMessage(message=JSONRPCResponse(jsonrpc="2.0", id=outbound.message.id, result={"ok": True}))
            )
            with anyio.fail_after(5):
                final = await s2c_recv.receive()
            assert isinstance(final, SessionMessage)
            assert isinstance(final.message, JSONRPCResponse)
            assert final.message.id == 7
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_ctx_progress_with_only_progress_value_omits_total_and_message():
    received: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        received.append((progress, total, message))

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        await ctx.progress(0.25)
        return {}

    async with running_pair(jsonrpc_pair, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            await client.send_raw_request("t", None, {"on_progress": on_progress})
    assert received == [(0.25, None, None)]


@pytest.mark.anyio
async def test_handler_raising_validation_error_sends_invalid_params():
    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        Tool.model_validate({"name": 123})  # raises ValidationError
        raise NotImplementedError

    async with running_pair(jsonrpc_pair, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.send_raw_request("t", None)
    assert exc.value.error.code == INVALID_PARAMS


@pytest.mark.anyio
async def test_send_raw_request_before_run_raises_runtimeerror():
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    d: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    try:
        with pytest.raises(RuntimeError, match="before run"):
            await d.send_raw_request("ping", None)
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_transport_exception_in_read_stream_is_logged_and_dropped():
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send)
    on_request, on_notify = echo_handlers(Recorder())
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, on_notify)
            await c2s_send.send(ValueError("transport hiccup"))
            # Dispatcher must remain healthy after the dropped exception.
            await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="t", params=None)))
            with anyio.fail_after(5):
                resp = await s2c_recv.receive()
            assert isinstance(resp, SessionMessage)
            assert isinstance(resp.message, JSONRPCResponse)
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_progress_notification_for_unknown_token_falls_through_to_on_notify():
    async with running_pair(jsonrpc_pair) as (client, _server, _crec, srec):
        with anyio.fail_after(5):
            await client.notify("notifications/progress", {"progressToken": 999, "progress": 0.5})
            await srec.notified.wait()
    assert srec.notifications == [("notifications/progress", {"progressToken": 999, "progress": 0.5})]


@pytest.mark.anyio
async def test_cancelled_notification_for_unknown_request_id_is_noop():
    async with running_pair(jsonrpc_pair) as (client, _server, _crec, srec):
        with anyio.fail_after(5):
            await client.notify("notifications/cancelled", {"requestId": 999})
            # No effect; dispatcher remains healthy.
            assert await client.send_raw_request("t", None) == {"echoed": "t", "params": {}}
    assert srec.notifications == []  # cancelled is fully consumed, never teed


_probe: contextvars.ContextVar[str] = contextvars.ContextVar("probe", default="unset")


@pytest.mark.anyio
async def test_handler_inherits_sender_contextvars_via_spawn():
    """The handler task sees contextvars set by the task that wrote into the read stream."""
    raw_send, raw_recv = anyio.create_memory_object_stream[tuple[contextvars.Context, SessionMessage | Exception]](4)
    read_stream = ContextReceiveStream[SessionMessage | Exception](raw_recv)
    write_send = ContextSendStream[SessionMessage | Exception](raw_send)
    out_send, out_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(read_stream, out_send)

    seen: list[str] = []

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        seen.append(_probe.get())
        return {}

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, server_on_request, on_notify)

            async def sender() -> None:
                _probe.set("from-sender")
                await write_send.send(
                    SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="t", params=None))
                )

            tg.start_soon(sender)
            with anyio.fail_after(5):
                resp = await out_recv.receive()
            assert isinstance(resp, SessionMessage)
            tg.cancel_scope.cancel()
    finally:
        for s in (raw_send, raw_recv, out_send, out_recv):
            s.close()
    assert seen == ["from-sender"]


@pytest.mark.anyio
async def test_response_write_after_peer_drop_is_swallowed():
    """Handler completes after the write stream is closed; the dropped write doesn't crash run()."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send)
    proceed = anyio.Event()
    handlers_done = anyio.Event()

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        await proceed.wait()
        if method == "raise":
            handlers_done.set()
            raise MCPError(code=INTERNAL_ERROR, message="x")
        return {"ok": True}

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, server_on_request, on_notify)
            await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="ok", params=None)))
            await c2s_send.send(
                SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=2, method="raise", params=None))
            )
            await anyio.sleep(0)
            # Peer drops: close the receive end so the server's writes hit BrokenResourceError.
            s2c_recv.close()
            proceed.set()
            with anyio.fail_after(5):
                await handlers_done.wait()
            # run() must still be healthy — close the read side to let it exit cleanly.
            c2s_send.close()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_cancel_outbound_after_write_stream_closed_is_swallowed():
    """Courtesy-cancel write hits a closed stream; the error is swallowed and cancellation propagates."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())
    caller_done = anyio.Event()
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            caller_scope = anyio.CancelScope()

            async def caller() -> None:
                with caller_scope:
                    await client.send_raw_request("slow", None)
                caller_done.set()

            tg.start_soon(caller)
            # Deterministic proof the request write completed: pull it off the wire.
            with anyio.fail_after(5):
                sent = await c2s_recv.receive()
            assert isinstance(sent, SessionMessage)
            assert isinstance(sent.message, JSONRPCRequest)
            # Now safe: close the client's write end, then cancel the caller. The
            # shielded `_cancel_outbound` write hits ClosedResourceError and is
            # swallowed; cancellation propagates cleanly.
            c2s_send.close()
            caller_scope.cancel()
            with anyio.fail_after(5):
                await caller_done.wait()
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


def test_resolve_pending_drops_outcome_when_waiter_stream_already_closed():
    """White-box: a response for an id still in _pending but whose waiter has gone."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    d: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    send, recv = anyio.create_memory_object_stream[dict[str, Any] | ErrorData](1)
    d._pending[1] = _Pending(send=send, receive=recv)  # pyright: ignore[reportPrivateUsage]
    recv.close()  # waiter gone — send_nowait will raise BrokenResourceError
    d._resolve_pending(1, {"late": True})  # pyright: ignore[reportPrivateUsage]
    for s in (c2s_send, c2s_recv, s2c_send, s2c_recv, send):
        s.close()


def test_fan_out_closed_drops_signal_when_waiter_already_has_outcome():
    """White-box: the buffer=1 invariant — WouldBlock means waiter already has an outcome."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    d: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    send, recv = anyio.create_memory_object_stream[dict[str, Any] | ErrorData](1)
    # Register a fake pending and pre-fill its single buffer slot.
    d._pending[1] = _Pending(send=send, receive=recv)  # pyright: ignore[reportPrivateUsage]
    send.send_nowait({"real": "result"})
    d._fan_out_closed()  # pyright: ignore[reportPrivateUsage]
    # The real result is still there; the close signal was dropped.
    assert recv.receive_nowait() == {"real": "result"}
    assert d._pending == {}  # pyright: ignore[reportPrivateUsage]
    for s in (c2s_send, c2s_recv, s2c_send, s2c_recv, send, recv):
        s.close()


def test_outbound_metadata_with_resumption_token_returns_client_metadata():
    md = _outbound_metadata(None, {"resumption_token": "abc"})
    assert isinstance(md, ClientMessageMetadata)
    assert md.resumption_token == "abc"
    assert _outbound_metadata(None, None) is None
    assert _outbound_metadata(None, {}) is None


@pytest.mark.anyio
async def test_jsonrpc_error_response_with_null_id_is_dropped():
    """Parse-error responses (id=null) have no waiter; they're logged and dropped."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            await s2c_send.send(
                SessionMessage(message=JSONRPCError(jsonrpc="2.0", id=None, error=ErrorData(code=-32700, message="x")))
            )
            await anyio.sleep(0)
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
