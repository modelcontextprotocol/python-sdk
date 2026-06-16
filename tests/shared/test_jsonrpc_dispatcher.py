"""JSON-RPC-specific dispatcher tests; contract tests shared with `DirectDispatcher` live in `test_dispatcher.py`."""

import contextvars
import json
import logging
from collections.abc import Mapping
from types import TracebackType
from typing import Any

import anyio
import anyio.lowlevel
import pytest
from mcp_types import (
    CONNECTION_CLOSED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    REQUEST_TIMEOUT,
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    CancelledNotification,
    CancelledNotificationParams,
    ErrorData,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    RequestId,
    Tool,
)
from trio.testing import MockClock

from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.shared._compat import resync_tracer
from mcp.shared._context_streams import ContextReceiveStream, ContextSendStream
from mcp.shared.dispatcher import CallOptions, DispatchContext
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.shared.jsonrpc_dispatcher import (  # pyright: ignore[reportPrivateUsage]
    JSONRPCDispatcher,
    _coerce_id,
    _OutboundPlan,
    _Pending,
    _plan_outbound,
)
from mcp.shared.message import ClientMessageMetadata, MessageMetadata, ServerMessageMetadata, SessionMessage
from mcp.shared.transport_context import TransportContext

from .conftest import jsonrpc_pair
from .test_dispatcher import Recorder, echo_handlers, running_pair

DCtx = DispatchContext[TransportContext]


class RecordingWriteStream:
    """Records sends without a checkpoint, so a pending cancellation cannot interrupt the write or mask it."""

    def __init__(self) -> None:
        self.sent: list[SessionMessage] = []

    async def send(self, item: SessionMessage) -> None:
        self.sent.append(item)

    async def aclose(self) -> None:
        raise NotImplementedError  # the dispatcher releases streams via __aexit__, never aclose

    async def __aenter__(self) -> "RecordingWriteStream":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        return None


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
async def test_handler_raising_exception_sends_code_zero_with_str_message():
    """Matches the existing server's `_handle_request`: code=0, message=str(e)."""

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        raise RuntimeError("kaboom")

    async with running_pair(jsonrpc_pair, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/list", None)
    assert exc.value.error.code == 0
    assert exc.value.error.message == "kaboom"
    assert exc.value.__cause__ is None  # cause does not survive the wire


@pytest.mark.anyio
async def test_peer_cancel_interrupt_mode_writes_cancelled_error_response():
    """Matches the existing server: a peer-cancelled request is answered with code=0."""
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

    seen_error: list[ErrorData] = []
    async with running_pair(jsonrpc_pair, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch

                async def call_then_record() -> None:
                    with pytest.raises(MCPError) as exc:
                        await client.send_raw_request("slow", None)
                    seen_error.append(exc.value.error)

                tg.start_soon(call_then_record)
                await handler_started.wait()
                await client.notify("notifications/cancelled", {"requestId": 1})
                await handler_exited.wait()
    assert seen_ctx[0].cancel_requested.is_set()
    assert seen_error == [ErrorData(code=0, message="Request cancelled")]


@pytest.mark.anyio
async def test_peer_cancel_landing_after_handlers_last_checkpoint_writes_only_the_result():
    """A peer cancel that fails to interrupt the handler writes only the result: one answer per
    id goes on the wire (SDK-defined). The recording stream is needed because a memory stream's
    `send` checkpoints, letting the deferred cancellation land mid-write and hide a double answer."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    recording = RecordingWriteStream()
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, recording)
    handler_started = anyio.Event()

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        handler_started.set()
        await ctx.cancel_requested.wait()
        return {"completed": "after-cancel"}

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        pass  # the cancelled notification is teed here; nothing to observe

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, on_notify)
            await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="t", params=None)))
            with anyio.fail_after(5):
                await handler_started.wait()
            # The cancel is also the handler's wakeup, so anyio defers it and the handler completes.
            await c2s_send.send(
                SessionMessage(
                    message=JSONRPCNotification(
                        jsonrpc="2.0", method="notifications/cancelled", params={"requestId": 1}
                    )
                )
            )
            # Quiesce: the handler has resumed, completed, and exited its scope.
            await anyio.wait_all_tasks_blocked()
            tg.cancel_scope.cancel()
    finally:
        c2s_send.close()
        c2s_recv.close()
    assert [m.message for m in recording.sent] == [
        JSONRPCResponse(jsonrpc="2.0", id=1, result={"completed": "after-cancel"})
    ]


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
async def test_run_returns_cleanly_when_read_stream_receive_end_is_closed():
    """Iterating a closed receive end is EOF, not a crash (stateless SHTTP closes it during teardown)."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send)
    on_request, on_notify = echo_handlers(Recorder())
    # Close the receive end itself (not the send end): __anext__ then raises ClosedResourceError.
    c2s_recv.close()
    with anyio.fail_after(5):
        await server.run(on_request, on_notify)
    for s in (c2s_send, s2c_send, s2c_recv):
        s.close()


@pytest.mark.anyio
async def test_run_cancels_in_flight_handlers_when_read_stream_eofs():
    """run() cancels still-running handlers at read-stream EOF; otherwise its join waits forever
    (over SSE, leaking the handler and the GET request hosting the session)."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send)
    handler_started = anyio.Event()
    handler_cancelled = anyio.Event()

    async def park(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        handler_started.set()
        try:
            await anyio.sleep_forever()
        finally:
            handler_cancelled.set()
        raise NotImplementedError

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    run_returned = anyio.Event()

    async def drive() -> None:
        await server.run(park, on_notify)
        run_returned.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(drive)
        await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="x", params=None)))
        with anyio.fail_after(5):
            await handler_started.wait()
            c2s_send.close()  # EOF the read side; run() must cancel the parked handler
            await run_returned.wait()
    assert handler_cancelled.is_set()
    s2c_recv.close()


@pytest.mark.anyio
async def test_run_closes_write_stream_after_clean_eof_without_drain_timeout():
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(
        c2s_recv,
        s2c_send,
        close_write_stream_on_read_close=False,
        read_eof_drain_timeout_seconds=None,
    )
    on_request, on_notify = echo_handlers(Recorder())

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg, c2s_send, c2s_recv, s2c_send, s2c_recv:
            await tg.start(server.run, on_request, on_notify)
            c2s_send.close()
            with pytest.raises(anyio.EndOfStream):  # pragma: no branch
                await s2c_recv.receive()


@pytest.mark.anyio
async def test_run_drains_in_flight_handlers_on_clean_eof_without_timeout():
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(
        c2s_recv,
        s2c_send,
        close_write_stream_on_read_close=False,
        read_eof_drain_timeout_seconds=None,
    )
    handler_started = anyio.Event()
    handler_allowed_to_finish = anyio.Event()

    async def handle_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        handler_started.set()
        await handler_allowed_to_finish.wait()
        return {"drained": True}

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg, c2s_send, c2s_recv, s2c_send, s2c_recv:
            await tg.start(server.run, handle_request, on_notify)
            await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="x", params=None)))
            await handler_started.wait()
            c2s_send.close()
            handler_allowed_to_finish.set()

            response = await s2c_recv.receive()
            assert isinstance(response, SessionMessage)
            assert isinstance(response.message, JSONRPCResponse)
            assert response.message.id == 1
            assert response.message.result == {"drained": True}


@pytest.mark.anyio
async def test_run_closes_write_stream_on_exit():
    """run() owns both streams; the write end is released once the EOF teardown completes."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send)
    on_request, on_notify = echo_handlers(Recorder())
    async with anyio.create_task_group() as tg:
        await tg.start(server.run, on_request, on_notify)
        c2s_send.close()  # EOF the read side; run() exits
        with anyio.fail_after(5), pytest.raises(anyio.EndOfStream):  # pragma: no branch
            await s2c_recv.receive()
    s2c_recv.close()


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
            # Let the parked handler respond to an id the client has already discarded.
            await handler_started.wait()
            proceed.set()
            # One more round-trip proves the dispatcher is still healthy.
            assert await client.send_raw_request("ping", None) == {"late": True}


@pytest.mark.anyio
async def test_raise_handler_exceptions_true_propagates_out_of_run():
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)

    def builder(_meta: object) -> TransportContext:
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
                await c2s_send.send(
                    SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="x", params=None))
                )
        assert exc.group_contains(RuntimeError, match="propagate me")
        # The error response was still written before re-raising.
        sent = s2c_recv.receive_nowait()
        assert isinstance(sent, SessionMessage)
        assert isinstance(sent.message, JSONRPCError)
        assert sent.message.error.code == 0
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
            await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=7, method="t", params=None)))
            with anyio.fail_after(5):
                outbound = await s2c_recv.receive()
            assert isinstance(outbound, SessionMessage)
            assert isinstance(outbound.message, JSONRPCRequest)
            assert isinstance(outbound.metadata, ServerMessageMetadata)
            assert outbound.metadata.related_request_id == 7
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
async def test_courtesy_cancel_on_timeout_tags_outbound_with_server_message_metadata():
    """The timeout-path `notifications/cancelled` carries the originating request id: SHTTP's
    `message_router` keys on `related_request_id`; without it the cancel would be dropped."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send)

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        with pytest.raises(MCPError):  # REQUEST_TIMEOUT
            await ctx.send_raw_request("sampling/createMessage", None, {"timeout": 0})
        return {"gave_up": True}

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, server_on_request, on_notify)
            await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=7, method="t", params=None)))
            with anyio.fail_after(5):
                outbound = await s2c_recv.receive()
            assert isinstance(outbound, SessionMessage)
            assert isinstance(outbound.message, JSONRPCRequest)
            assert outbound.message.method == "sampling/createMessage"
            sampling_id = outbound.message.id
            # Don't respond; let the timeout fire. Next on the wire is the courtesy cancel.
            with anyio.fail_after(5):
                cancel = await s2c_recv.receive()
            assert isinstance(cancel, SessionMessage)
            assert isinstance(cancel.message, JSONRPCNotification)
            assert cancel.message.method == "notifications/cancelled"
            assert cancel.message.params == {"requestId": sampling_id, "reason": "timed out after 0s"}
            assert isinstance(cancel.metadata, ServerMessageMetadata)
            assert cancel.metadata.related_request_id == 7
            with anyio.fail_after(5):
                final = await s2c_recv.receive()
            assert isinstance(final, SessionMessage)
            assert isinstance(final.message, JSONRPCResponse)
            assert final.message.result == {"gave_up": True}
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_dispatch_context_request_with_dropped_resumption_hints_still_sends_courtesy_cancel():
    """Resumption hints that never reach the transport must not suppress the abandon cancel:
    `related_request_id` takes metadata precedence and drops the hints, so the request is not resumable."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send)

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        with pytest.raises(MCPError):  # REQUEST_TIMEOUT
            await ctx.send_raw_request("sampling/createMessage", None, {"timeout": 0, "resumption_token": "tok"})
        return {"gave_up": True}

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, server_on_request, on_notify)
            await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=7, method="t", params=None)))
            with anyio.fail_after(5):
                outbound = await s2c_recv.receive()
            assert isinstance(outbound, SessionMessage)
            assert isinstance(outbound.message, JSONRPCRequest)
            # The hints were dropped: dispatch-context routing won the metadata.
            assert isinstance(outbound.metadata, ServerMessageMetadata)
            sampling_id = outbound.message.id
            # Don't respond; let the timeout fire. Next on the wire must be the courtesy cancel.
            with anyio.fail_after(5):
                cancel = await s2c_recv.receive()
            assert isinstance(cancel, SessionMessage)
            assert isinstance(cancel.message, JSONRPCNotification)
            assert cancel.message.method == "notifications/cancelled"
            assert cancel.message.params == {"requestId": sampling_id, "reason": "timed out after 0s"}
            with anyio.fail_after(5):
                final = await s2c_recv.receive()
            assert isinstance(final, SessionMessage)
            assert isinstance(final.message, JSONRPCResponse)
            assert final.message.result == {"gave_up": True}
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_caller_cancel_sends_courtesy_cancellation_on_the_wire():
    """Cancelling the scope around send_raw_request emits notifications/cancelled by default."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())

    scopes: list[anyio.CancelScope] = []
    gave_up = anyio.Event()

    async def caller() -> None:
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            await client.send_raw_request("slow", None)
            raise NotImplementedError  # unreachable: the scope is cancelled
        gave_up.set()

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            tg.start_soon(caller)
            with anyio.fail_after(5):
                request = await c2s_recv.receive()
            assert isinstance(request, SessionMessage)
            assert isinstance(request.message, JSONRPCRequest)
            scopes[0].cancel()
            with anyio.fail_after(5):
                await gave_up.wait()
                cancel = await c2s_recv.receive()
            assert isinstance(cancel, SessionMessage)
            assert isinstance(cancel.message, JSONRPCNotification)
            assert cancel.message.method == "notifications/cancelled"
            assert cancel.message.params == {"requestId": request.message.id, "reason": "caller cancelled"}
            assert cancel.metadata is None
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
    assert scopes[0].cancelled_caught


@pytest.mark.anyio
async def test_caller_cancel_during_blocked_request_write_still_sends_courtesy_cancellation():
    """A request write interrupted by cancellation may still have delivered its message, so the
    courtesy cancel goes out anyway: the peer drops cancels for ids it never saw, while skipping
    the cancel would leak a delivered request's handler. The fake stream wedges only the first
    write, so the courtesy cancel itself still lands."""

    class FirstWriteWedgedStream:
        def __init__(self) -> None:
            self.sent: list[SessionMessage] = []
            self.first_write_started = anyio.Event()

        async def send(self, item: SessionMessage) -> None:
            if not self.first_write_started.is_set():
                self.first_write_started.set()
                await anyio.sleep_forever()  # the request write wedges until the caller is cancelled
            self.sent.append(item)

        async def aclose(self) -> None:
            raise NotImplementedError

        async def __aenter__(self) -> "FirstWriteWedgedStream":
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
        ) -> bool | None:
            return None

    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    wedged = FirstWriteWedgedStream()
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, wedged)
    on_request, on_notify = echo_handlers(Recorder())

    scopes: list[anyio.CancelScope] = []
    gave_up = anyio.Event()

    async def caller() -> None:
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            await client.send_raw_request("slow", None)
            raise NotImplementedError  # unreachable: the scope is cancelled
        gave_up.set()

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            tg.start_soon(caller)
            with anyio.fail_after(5):
                await wedged.first_write_started.wait()  # the caller is parked in the request write
            scopes[0].cancel()
            with anyio.fail_after(5):
                await gave_up.wait()
            await client.notify("notifications/marker", None)
            tg.cancel_scope.cancel()
    finally:
        await resync_tracer()
        s2c_send.close()
        s2c_recv.close()
    assert scopes[0].cancelled_caught
    # The wedged request write started, so it counts as issued: the cancel precedes the marker.
    assert [m.message for m in wedged.sent] == [
        JSONRPCNotification(
            jsonrpc="2.0", method="notifications/cancelled", params={"requestId": 1, "reason": "caller cancelled"}
        ),
        JSONRPCNotification(jsonrpc="2.0", method="notifications/marker"),
    ]


@pytest.mark.anyio
async def test_caller_cancel_during_delivered_request_write_sends_courtesy_cancellation():
    """A cancelled request write may still deliver: on a buffer-0 stream the transport can pop the
    parked request in the same tick the cancel lands, so send() raises CancelledError after handing
    the message over. The peer saw the id, so the courtesy cancel must still go out."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())

    scopes: list[anyio.CancelScope] = []
    gave_up = anyio.Event()

    async def caller() -> None:
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            await client.send_raw_request("slow", None)
            raise NotImplementedError  # unreachable: the scope is cancelled
        gave_up.set()

    async def marker_after_caller_unwinds() -> None:
        # Without the courtesy cancel, the marker is the next message: a missing
        # cancel fails the assertion below instead of hanging the receive.
        await gave_up.wait()
        await client.notify("notifications/marker", None)

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            tg.start_soon(caller)
            await anyio.wait_all_tasks_blocked()  # the caller is parked in the buffer-0 request write
            scopes[0].cancel()  # the cancel lands on the parked send() first...
            request = c2s_recv.receive_nowait()  # ...then the transport pops the request: delivered
            assert isinstance(request, SessionMessage)
            assert isinstance(request.message, JSONRPCRequest)
            tg.start_soon(marker_after_caller_unwinds)
            with anyio.fail_after(5):
                cancel = await c2s_recv.receive()
            assert isinstance(cancel, SessionMessage)
            assert cancel.message == JSONRPCNotification(
                jsonrpc="2.0",
                method="notifications/cancelled",
                params={"requestId": request.message.id, "reason": "caller cancelled"},
            )
            with anyio.fail_after(5):
                marker = await c2s_recv.receive()
            assert isinstance(marker, SessionMessage)
            assert marker.message == JSONRPCNotification(jsonrpc="2.0", method="notifications/marker")
            tg.cancel_scope.cancel()
    finally:
        await resync_tracer()
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
    assert scopes[0].cancelled_caught


@pytest.mark.anyio
async def test_caller_cancelled_before_request_write_starts_sends_no_courtesy_cancellation():
    """A caller whose scope is already cancelled never gets the request onto the wire, so no
    courtesy cancel goes out either: there is provably no id for the peer to stop."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())

    scopes: list[anyio.CancelScope] = []
    gave_up = anyio.Event()

    async def caller() -> None:
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            scope.cancel()  # already cancelled when send_raw_request runs: the write never starts
            await client.send_raw_request("slow", None)
            raise NotImplementedError  # unreachable: the scope is cancelled
        gave_up.set()

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            tg.start_soon(caller)
            with anyio.fail_after(5):
                await gave_up.wait()
            # A request or courtesy cancel would have to precede the marker on the ordered stream.
            await client.notify("notifications/marker", None)
            with anyio.fail_after(5):
                first = await c2s_recv.receive()
            assert isinstance(first, SessionMessage)
            assert first.message == JSONRPCNotification(jsonrpc="2.0", method="notifications/marker")
            tg.cancel_scope.cancel()
    finally:
        await resync_tracer()
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
    assert scopes[0].cancelled_caught


@pytest.mark.anyio
async def test_caller_cancel_with_resumption_hints_suppresses_the_courtesy_cancellation():
    """A request sent with resumption hints is meant to be resumed; abandoning it must not stop the peer's work."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())

    async def on_token(token: str) -> None:
        raise NotImplementedError

    scopes: list[anyio.CancelScope] = []
    gave_up = anyio.Event()

    async def caller() -> None:
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            await client.send_raw_request("slow", None, {"on_resumption_token": on_token})
            raise NotImplementedError  # unreachable: the scope is cancelled
        gave_up.set()

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            tg.start_soon(caller)
            with anyio.fail_after(5):
                request = await c2s_recv.receive()
            assert isinstance(request, SessionMessage)
            assert isinstance(request.message, JSONRPCRequest)
            scopes[0].cancel()
            with anyio.fail_after(5):
                await gave_up.wait()
            # A courtesy cancel would have to precede the marker on the ordered stream.
            await client.notify("marker", None)
            with anyio.fail_after(5):
                nxt = await c2s_recv.receive()
            assert isinstance(nxt, SessionMessage)
            assert isinstance(nxt.message, JSONRPCNotification)
            assert nxt.message.method == "marker"
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_timeout_with_resumption_hints_suppresses_the_courtesy_cancellation():
    """A timed-out request that carries resumption hints stays resumable: no cancellation is sent."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            with anyio.fail_after(5):
                with pytest.raises(MCPError) as exc:
                    await client.send_raw_request("slow", None, {"timeout": 0, "resumption_token": "tok"})
            assert exc.value.error.code == REQUEST_TIMEOUT
            with anyio.fail_after(5):
                request = await c2s_recv.receive()
            assert isinstance(request, SessionMessage)
            assert isinstance(request.message, JSONRPCRequest)
            await client.notify("marker", None)
            with anyio.fail_after(5):
                nxt = await c2s_recv.receive()
            assert isinstance(nxt, SessionMessage)
            assert isinstance(nxt.message, JSONRPCNotification)
            assert nxt.message.method == "marker"
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_cancel_on_abandon_false_suppresses_the_courtesy_cancellation_on_timeout():
    """Callers opt out per call for requests the protocol forbids cancelling (initialize)."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            with anyio.fail_after(5):
                with pytest.raises(MCPError) as exc:
                    await client.send_raw_request("slow", None, {"timeout": 0, "cancel_on_abandon": False})
            assert exc.value.error.code == REQUEST_TIMEOUT
            with anyio.fail_after(5):
                request = await c2s_recv.receive()
            assert isinstance(request, SessionMessage)
            assert isinstance(request.message, JSONRPCRequest)
            await client.notify("marker", None)
            with anyio.fail_after(5):
                nxt = await c2s_recv.receive()
            assert isinstance(nxt, SessionMessage)
            assert isinstance(nxt.message, JSONRPCNotification)
            assert nxt.message.method == "marker"
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


class TimingOutWriteStream:
    """`send()` raises builtin `TimeoutError`, like a custom transport whose bounded send expired."""

    def __init__(self) -> None:
        self.attempts = 0
        self.error = TimeoutError("transport send timed out")

    async def send(self, item: SessionMessage) -> None:
        self.attempts += 1
        raise self.error

    async def aclose(self) -> None:
        raise NotImplementedError  # the dispatcher releases streams via __aexit__, never aclose

    async def __aenter__(self) -> "TimingOutWriteStream":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        return None


@pytest.mark.anyio
async def test_transport_write_timeout_propagates_raw_when_no_request_timeout_is_set():
    """A builtin TimeoutError from the transport's own bounded `send()` is a transport failure,
    not `opts["timeout"]` elapsing — no timeout is set here, so `fail_after(None)` cannot have
    fired — and must propagate raw instead of being mislabelled REQUEST_TIMEOUT. (Genuine expiry
    after a completed write is pinned by the timeout tests above and
    `test_timeout_courtesy_cancel_write_is_bounded_when_the_transport_is_wedged`.)"""
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    transport = TimingOutWriteStream()
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, transport)
    on_request, on_notify = echo_handlers(Recorder())

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            with anyio.fail_after(5):
                with pytest.raises(TimeoutError) as exc:
                    await client.send_raw_request("tools/call", {"name": "x"}, None)
            assert exc.value is transport.error  # the exact instance propagated unwrapped
            # The request never reached the peer, so no courtesy cancel may follow the failed write.
            assert transport.attempts == 1
            tg.cancel_scope.cancel()
    finally:
        await resync_tracer()
        s2c_send.close()
        s2c_recv.close()


@pytest.mark.parametrize(
    "anyio_backend",
    [pytest.param(("trio", {"clock": MockClock(autojump_threshold=0)}), id="trio-mockclock")],
)
@pytest.mark.anyio
async def test_caller_cancel_courtesy_write_is_bounded_when_the_transport_is_wedged(
    caplog: pytest.LogCaptureFixture,
):
    """A wedged transport write cannot turn caller cancellation into an unbounded shielded hang:
    `_ABANDON_WRITE_TIMEOUT` abandons the courtesy-cancel write (SDK-defined bound). On regression
    the test hangs rather than failing fast - fail_after cannot cancel through the shield."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())

    scopes: list[anyio.CancelScope] = []
    gave_up = anyio.Event()

    async def caller() -> None:
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            await client.send_raw_request("slow", None)
            raise NotImplementedError  # unreachable: the scope is cancelled
        gave_up.set()

    try:
        # Both bounds exceed the in-loop _ABANDON_WRITE_TIMEOUT (5s); the virtual clock makes them instant.
        with anyio.fail_after(30):
            async with anyio.create_task_group() as tg:  # pragma: no branch
                await tg.start(client.run, on_request, on_notify)
                tg.start_soon(caller)
                # Consume only the request; the later courtesy cancel finds no reader and wedges.
                request = await c2s_recv.receive()
                assert isinstance(request, SessionMessage)
                assert isinstance(request.message, JSONRPCRequest)
                scopes[0].cancel()
                with anyio.fail_after(20):
                    await gave_up.wait()
                tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
    assert scopes[0].cancelled_caught
    # The warning proves it was the bound (not a completed write) that released the shield.
    assert "courtesy cancel for caller-cancelled request" in caplog.text


@pytest.mark.parametrize(
    "anyio_backend",
    [pytest.param(("trio", {"clock": MockClock(autojump_threshold=0)}), id="trio-mockclock")],
)
@pytest.mark.anyio
async def test_timeout_courtesy_cancel_write_is_bounded_when_the_transport_is_wedged(
    caplog: pytest.LogCaptureFixture,
):
    """A wedged transport write cannot delay the REQUEST_TIMEOUT error indefinitely (SDK-defined
    bound): `_ABANDON_WRITE_TIMEOUT` abandons the courtesy cancel so the error still surfaces."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())

    errors: list[MCPError] = []
    gave_up = anyio.Event()

    async def caller() -> None:
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("slow", None, {"timeout": 1})
        errors.append(exc.value)
        gave_up.set()

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            tg.start_soon(caller)
            # Consume only the request; the later courtesy cancel finds no reader and wedges.
            with anyio.fail_after(5):
                request = await c2s_recv.receive()
            assert isinstance(request, SessionMessage)
            assert isinstance(request.message, JSONRPCRequest)
            # Exceeds the request timeout (1s) plus _ABANDON_WRITE_TIMEOUT (5s); virtual clock, no wall time.
            with anyio.fail_after(10):
                await gave_up.wait()
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
    assert errors[0].error.code == REQUEST_TIMEOUT
    assert "courtesy cancel for timed-out request" in caplog.text


@pytest.mark.parametrize(
    "anyio_backend",
    [pytest.param(("trio", {"clock": MockClock(autojump_threshold=0)}), id="trio-mockclock")],
)
@pytest.mark.anyio
async def test_shutdown_error_response_write_is_bounded_when_the_transport_is_wedged(
    caplog: pytest.LogCaptureFixture,
):
    """Cancelling the task group hosting run() completes even when the shutdown error write wedges:
    only `_SHUTDOWN_WRITE_TIMEOUT` releases the join (SDK-defined). A 0-buffer stream nobody reads
    expresses the wedge: drain-mode run() closes its write stream only after the join, so the send stays parked."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(
        c2s_recv,
        s2c_send,
        close_write_stream_on_read_close=False,
    )
    handler_started = anyio.Event()

    async def park(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        handler_started.set()
        await anyio.sleep_forever()
        raise NotImplementedError

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    try:
        # 3s sits between _SHUTDOWN_WRITE_TIMEOUT (1s) and _ABANDON_WRITE_TIMEOUT (5s): pins the tighter bound.
        with anyio.fail_after(3):
            async with anyio.create_task_group() as tg:  # pragma: no branch
                await tg.start(server.run, park, on_notify)
                await c2s_send.send(
                    SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="t", params=None))
                )
                await handler_started.wait()
                tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
    # The warning proves the bound (not a completed write) released the join.
    assert "shutdown error response for request" in caplog.text


@pytest.mark.anyio
async def test_shutdown_answers_in_flight_request_with_connection_closed():
    """Read-stream EOF answers a still-running request with CONNECTION_CLOSED (SDK-defined):
    drain-mode run() keeps the write stream open until the task-group join, so the shielded teardown write lands."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(
        c2s_recv,
        s2c_send,
        close_write_stream_on_read_close=False,
        read_eof_drain_timeout_seconds=0.05,
    )
    handler_started = anyio.Event()

    async def park(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        handler_started.set()
        await anyio.sleep_forever()
        raise NotImplementedError

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, park, on_notify)
            await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="t", params=None)))
            with anyio.fail_after(5):
                await handler_started.wait()
            c2s_send.close()  # EOF: run() cancels the parked handler, which must still answer
            with anyio.fail_after(5):
                answer = await s2c_recv.receive()
            assert isinstance(answer, SessionMessage)
            assert answer.message == JSONRPCError(
                jsonrpc="2.0", id=1, error=ErrorData(code=CONNECTION_CLOSED, message="Connection closed")
            )
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_shutdown_cancel_during_delivered_result_write_writes_no_second_answer():
    """A result write can deliver its message and still raise CancelledError: on a buffer-0 stream
    the transport pops the parked send in the same tick the shutdown cancel lands. The shutdown arm
    must not stack a CONNECTION_CLOSED answer on top - one request id, at most one answer (peers
    drop a missing answer via their own close fan-out, but a duplicate id breaks JSON-RPC)."""
    read_send, read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    write_send, write_recv = anyio.create_memory_object_stream[SessionMessage](0)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(read_recv, write_send)
    on_request, on_notify = echo_handlers(Recorder())
    outer = anyio.CancelScope()

    async def run_server() -> None:
        with outer:
            await server.run(on_request, on_notify)

    received: list[SessionMessage] = []
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(run_server)
            await read_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=7, method="t", params=None)))
            await anyio.wait_all_tasks_blocked()  # the handler is parked in the buffer-0 result write
            outer.cancel()  # the shutdown cancel lands on the parked send() first...
            received.append(write_recv.receive_nowait())  # ...then the transport pops the result: delivered
            stream_closed = False
            with anyio.fail_after(5):
                try:
                    # run() closes its write stream on exit; any second answer would arrive before that.
                    received.append(await write_recv.receive())
                except anyio.EndOfStream:
                    stream_closed = True
            assert stream_closed
    finally:
        await resync_tracer()
        for s in (read_send, read_recv, write_send, write_recv):
            s.close()
    assert outer.cancelled_caught
    assert [m.message for m in received] == [JSONRPCResponse(jsonrpc="2.0", id=7, result={"echoed": "t", "params": {}})]


@pytest.mark.anyio
async def test_request_write_failure_propagates_and_leaves_no_pending_entry():
    """A request whose transport write raises must not leak its `_pending` entry (v1 regression cover)."""
    boom = RuntimeError("write failed")

    class RaisingWriteStream:
        async def send(self, item: SessionMessage) -> None:
            raise boom

        async def aclose(self) -> None:
            raise NotImplementedError

        async def __aenter__(self) -> "RaisingWriteStream":
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
        ) -> bool | None:
            return None

    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, RaisingWriteStream())
    on_request, on_notify = echo_handlers(Recorder())
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            with anyio.fail_after(5), pytest.raises(RuntimeError) as exc:
                await client.send_raw_request("ping", None)
            assert exc.value is boom
            assert client._pending == {}  # pyright: ignore[reportPrivateUsage]
            tg.cancel_scope.cancel()
    finally:
        s2c_send.close()
        s2c_recv.close()


@pytest.mark.anyio
async def test_request_write_on_torn_down_transport_raises_connection_closed():
    """A write onto a torn-down transport surfaces as MCPError(CONNECTION_CLOSED), not a raw `BrokenResourceError`."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            # Close only the peer's receive end, so run() has not observed EOF when the write fails.
            c2s_recv.close()
            with anyio.fail_after(5), pytest.raises(MCPError) as exc:
                await client.send_raw_request("ping", None)
            assert exc.value.error.code == CONNECTION_CLOSED
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_notify_after_connection_close_is_dropped_with_debug_log(caplog: pytest.LogCaptureFixture):
    """notify() after run() saw EOF is fire-and-forget: dropped with a debug log,
    matching the response-write policy, while the sibling send_raw_request raises."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())
    try:
        s2c_send.close()  # peer drops: run() sees immediate EOF and returns
        with anyio.fail_after(5):
            await client.run(on_request, on_notify)
        with caplog.at_level(logging.DEBUG, logger="mcp.shared.jsonrpc_dispatcher"):
            await client.notify("notifications/roots/list_changed", None)
        assert "dropped notifications/roots/list_changed: dispatcher closed" in caplog.text
        with pytest.raises(anyio.EndOfStream):
            c2s_recv.receive_nowait()  # nothing reached the wire
    finally:
        await resync_tracer()
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_notify_on_torn_down_transport_is_dropped_with_debug_log(caplog: pytest.LogCaptureFixture):
    """A notify racing transport teardown (run() hasn't seen EOF yet) is dropped, not a raw `BrokenResourceError`."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            # Close only the peer's receive end, so run() has not observed EOF when the write fails.
            c2s_recv.close()
            with caplog.at_level(logging.DEBUG, logger="mcp.shared.jsonrpc_dispatcher"), anyio.fail_after(5):
                await client.notify("notifications/roots/list_changed", None)
            assert "dropped notifications/roots/list_changed: write stream closed" in caplog.text
            tg.cancel_scope.cancel()
    finally:
        await resync_tracer()
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_notification_handler_exception_is_contained(caplog: pytest.LogCaptureFixture):
    """A raising notification handler costs only that notification, never the connection (parity with TS/C#/Go)."""

    async def server_on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        raise RuntimeError("notify boom")

    async with running_pair(jsonrpc_pair, server_on_notify=server_on_notify) as (client, *_):
        with anyio.fail_after(5):
            await client.notify("boom", None)
            # The connection survived: a full round-trip still works.
            result = await client.send_raw_request("ping", None)
    assert result == {"echoed": "ping", "params": {}}
    assert "notification handler for 'boom' raised" in caplog.text


@pytest.mark.anyio
async def test_spawned_notification_handlers_run_concurrently():
    """Notification handlers are spawned, not serialized (parity with TS/C#): the first handler
    waits for the second to start, so serialized dispatch would deadlock here."""
    second_started = anyio.Event()
    completed: list[str] = []
    done = anyio.Event()

    async def server_on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        if method == "first":
            await second_started.wait()
        else:
            second_started.set()
        completed.append(method)
        if len(completed) == 2:
            done.set()

    async with running_pair(jsonrpc_pair, server_on_notify=server_on_notify) as (client, *_):
        with anyio.fail_after(5):
            await client.notify("first", None)
            await client.notify("second", None)
            await done.wait()
    assert completed == ["second", "first"]


@pytest.mark.anyio
async def test_ctx_message_metadata_carries_inbound_request_metadata():
    """Transport-attached metadata (HTTP request, SSE close hooks) is readable off the dispatch context."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send)
    metadata = ServerMessageMetadata(request_context="request-scoped-data")
    seen: list[MessageMetadata] = []

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        seen.append(ctx.message_metadata)
        return {}

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, on_notify)
            await c2s_send.send(
                SessionMessage(
                    message=JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/call", params=None),
                    metadata=metadata,
                )
            )
            with anyio.fail_after(5):
                await s2c_recv.receive()  # response sent => the handler has run
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
    assert len(seen) == 1
    assert seen[0] is metadata  # the exact object, passed through verbatim


@pytest.mark.anyio
async def test_ctx_message_metadata_carries_inbound_notification_metadata():
    """Notifications get the same metadata pass-through as requests."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send)
    metadata = ServerMessageMetadata(request_context="request-scoped-data")
    seen: list[MessageMetadata] = []
    notified = anyio.Event()

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        raise NotImplementedError

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        seen.append(ctx.message_metadata)
        notified.set()

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, on_notify)
            await c2s_send.send(
                SessionMessage(
                    message=JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized", params=None),
                    metadata=metadata,
                )
            )
            with anyio.fail_after(5):
                await notified.wait()
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
    assert len(seen) == 1
    assert seen[0] is metadata


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
async def test_ctx_after_handler_return_reports_closed_and_drops_backchannel_traffic():
    """After `_handle_request` closes the dctx, `can_send_request` is False, `send_raw_request` raises
    NoBackChannelError, and `notify`/`progress` are dropped rather than sent with a stale `related_request_id`."""
    captured: list[DCtx] = []

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        captured.append(ctx)
        assert ctx.can_send_request is True
        return {}

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        raise NotImplementedError

    async with running_pair(jsonrpc_pair, server_on_request=server_on_request) as (client, _server, crec, _srec):
        with anyio.fail_after(5):
            await client.send_raw_request("tools/call", None, {"on_progress": on_progress})
            dctx = captured[0]
            assert dctx.can_send_request is False
            with pytest.raises(NoBackChannelError):
                await dctx.send_raw_request("sampling/createMessage", None)
            await dctx.notify("notifications/message", {"level": "info"})
            await dctx.progress(0.9)
            # A second round-trip flushes any server write; an empty recorder then proves the drop.
            await client.send_raw_request("ping", None)
        assert crec.notifications == []


@pytest.mark.anyio
async def test_progress_callback_exception_is_swallowed_and_logged(caplog: pytest.LogCaptureFixture):
    """A user progress callback raising must not crash the dispatcher."""

    async def boom(progress: float, total: float | None, message: str | None) -> None:
        raise RuntimeError("progress callback boom")

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        await ctx.progress(0.5)
        return {"ok": True}

    opts: CallOptions = {"on_progress": boom}
    async with running_pair(jsonrpc_pair, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            result = await client.send_raw_request("t", None, opts)
    assert result == {"ok": True}
    assert "progress callback raised" in caplog.text


@pytest.mark.anyio
async def test_inline_methods_are_handled_before_next_message_is_dequeued():
    """An `inline_methods` method runs to completion before the next message is dispatched."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(
        c2s_recv, s2c_send, inline_methods=frozenset({"first"})
    )
    state = {"initialized": False}
    seen: list[bool] = []

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        if method == "first":
            await anyio.lowlevel.checkpoint()
            state["initialized"] = True
        else:
            seen.append(state["initialized"])
        return {}

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    # Buffer both requests before run() reads anything.
    await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="first", params=None)))
    await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=2, method="second", params=None)))
    c2s_send.close()
    with anyio.fail_after(5):
        await server.run(on_request, on_notify)
    assert seen == [True]
    s2c_recv.close()


@pytest.mark.anyio
async def test_send_raw_request_always_carries_meta_on_the_wire():
    """Outbound requests always carry `params._meta` (otel injection per SEP-414); caller-supplied
    keys are preserved and the progress token is merged in."""
    seen: list[Mapping[str, Any] | None] = []

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        seen.append(params)
        return {}

    async def noop_progress(progress: float, total: float | None, message: str | None) -> None:
        raise NotImplementedError

    opts: CallOptions = {"on_progress": noop_progress}
    async with running_pair(jsonrpc_pair, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            await client.send_raw_request("a", None)
            await client.send_raw_request("b", {"x": 1, "_meta": {"k": "v"}}, opts)
    # `_meta` contents depend on the active otel tracer, so pin only what sits beyond the W3C keys.
    w3c = {"traceparent", "tracestate"}
    assert seen[0] is not None and seen[0].keys() == {"_meta"}
    assert set(seen[0]["_meta"].keys()) <= w3c
    assert seen[1] is not None and seen[1]["x"] == 1
    assert set(seen[1]["_meta"].keys()) - w3c == {"k", "progressToken"}
    assert seen[1]["_meta"]["k"] == "v"


@pytest.mark.anyio
async def test_handler_raising_validation_error_sends_invalid_params():
    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        Tool.model_validate({"name": 123})  # raises ValidationError
        raise NotImplementedError

    async with running_pair(jsonrpc_pair, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.send_raw_request("t", None)
    assert exc.value.error == ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")


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
async def test_send_raw_request_after_connection_close_raises_connection_closed():
    """Sending after run() saw EOF raises MCPError(CONNECTION_CLOSED) — the same contract
    in-flight waiters get — not RuntimeError (SDK-defined)."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())
    try:
        s2c_send.close()  # peer drops: run() sees immediate EOF and returns
        with anyio.fail_after(5):
            await client.run(on_request, on_notify)
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("ping", None)
        assert exc.value.error.code == CONNECTION_CLOSED
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
async def test_on_stream_exception_observes_transport_exceptions():
    """With an observer set, Exception items reach it instead of being dropped; the loop stays healthy."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)

    seen: list[Exception] = []

    async def observe(exc: Exception) -> None:
        seen.append(exc)

    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send, on_stream_exception=observe)
    on_request, on_notify = echo_handlers(Recorder())
    hiccup = ValueError("transport hiccup")
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, on_notify)
            await c2s_send.send(hiccup)
            await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="t", params=None)))
            with anyio.fail_after(5):
                resp = await s2c_recv.receive()
            assert isinstance(resp, SessionMessage)
            assert isinstance(resp.message, JSONRPCResponse)
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
    assert seen == [hiccup]


@pytest.mark.anyio
async def test_on_stream_exception_observer_raising_is_contained(caplog: pytest.LogCaptureFixture):
    """A raising observer costs the item, not the connection: it runs in the read loop itself."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)

    async def observe(exc: Exception) -> None:
        raise RuntimeError("observer boom")

    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send, on_stream_exception=observe)
    on_request, on_notify = echo_handlers(Recorder())
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, on_notify)
            await c2s_send.send(ValueError("transport hiccup"))
            await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="t", params=None)))
            with anyio.fail_after(5):
                resp = await s2c_recv.receive()
            assert isinstance(resp, SessionMessage)
            assert isinstance(resp.message, JSONRPCResponse)
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
    assert "on_stream_exception observer raised" in caplog.text


@pytest.mark.anyio
async def test_progress_notification_for_unknown_token_falls_through_to_on_notify():
    async with running_pair(jsonrpc_pair) as (client, _server, _crec, srec):
        with anyio.fail_after(5):
            await client.notify("notifications/progress", {"progressToken": 999, "progress": 0.5})
            await srec.notified.wait()
    assert srec.notifications == [("notifications/progress", {"progressToken": 999, "progress": 0.5})]


@pytest.mark.anyio
async def test_cancelled_notification_for_unknown_request_id_skips_cancel_but_reaches_on_notify():
    async with running_pair(jsonrpc_pair) as (client, _server, _crec, srec):
        with anyio.fail_after(5):
            await client.notify("notifications/cancelled", {"requestId": 999})
            await srec.notified.wait()
            # No in-flight correlation; dispatcher remains healthy.
            assert await client.send_raw_request("t", None) == {"echoed": "t", "params": {}}
    # cancelled is teed to on_notify so middleware/handlers can observe it.
    assert srec.notifications == [("notifications/cancelled", {"requestId": 999})]


@pytest.mark.anyio
async def test_cancelled_notification_for_in_flight_request_is_teed_to_on_notify():
    """The dispatcher applies the cancellation itself AND forwards the notification."""
    handler_started = anyio.Event()
    handler_exited = anyio.Event()

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        handler_started.set()
        try:
            await anyio.sleep_forever()
        finally:
            handler_exited.set()
        raise NotImplementedError

    async with running_pair(jsonrpc_pair, server_on_request=server_on_request) as (client, _server, _crec, srec):
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch

                async def call() -> None:
                    with pytest.raises(MCPError):
                        await client.send_raw_request("slow", None)

                tg.start_soon(call)
                await handler_started.wait()
                await client.notify("notifications/cancelled", {"requestId": 1})
                await handler_exited.wait()
                await srec.notified.wait()
    assert srec.notifications == [("notifications/cancelled", {"requestId": 1})]


_probe: contextvars.ContextVar[str] = contextvars.ContextVar("probe", default="unset")


@pytest.mark.anyio
@pytest.mark.parametrize("inline", [frozenset[str](), frozenset({"t"})], ids=["spawned", "inline"])
async def test_handler_inherits_sender_contextvars(inline: frozenset[str]):
    """The handler sees the sender's contextvars on both the spawned and the inline-method dispatch paths."""
    raw_send, raw_recv = anyio.create_memory_object_stream[tuple[contextvars.Context, SessionMessage | Exception]](4)
    read_stream = ContextReceiveStream[SessionMessage | Exception](raw_recv)
    write_send = ContextSendStream[SessionMessage | Exception](raw_send)
    out_send, out_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(read_stream, out_send, inline_methods=inline)

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
            # run() must still be healthy - close the read side to let it exit cleanly.
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
            # The shielded `_cancel_outbound` write now hits ClosedResourceError and is swallowed.
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
    recv.close()  # waiter gone - send_nowait will raise BrokenResourceError
    d._resolve_pending(1, {"late": True})  # pyright: ignore[reportPrivateUsage]
    for s in (c2s_send, c2s_recv, s2c_send, s2c_recv, send):
        s.close()


def test_fan_out_closed_drops_signal_when_waiter_already_has_outcome():
    """White-box: the buffer=1 invariant - WouldBlock means waiter already has an outcome."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    d: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    send, recv = anyio.create_memory_object_stream[dict[str, Any] | ErrorData](1)
    d._pending[1] = _Pending(send=send, receive=recv)  # pyright: ignore[reportPrivateUsage]
    send.send_nowait({"real": "result"})
    d._fan_out_closed()  # pyright: ignore[reportPrivateUsage]
    # The real result is still there; the close signal was dropped.
    assert recv.receive_nowait() == {"real": "result"}
    assert d._pending == {}  # pyright: ignore[reportPrivateUsage]
    for s in (c2s_send, c2s_recv, s2c_send, s2c_recv, send, recv):
        s.close()


def test_plan_outbound_with_resumption_token_returns_client_metadata_and_suppresses_abandon_cancel():
    """Hints that reach the transport make the request resumable, so abandoning it must not cancel the peer's work."""
    plan = _plan_outbound(None, {"resumption_token": "abc"})
    assert isinstance(plan.metadata, ClientMessageMetadata)
    assert plan.metadata.resumption_token == "abc"
    assert plan.cancel_on_abandon is False
    assert _plan_outbound(None, None) == _OutboundPlan(metadata=None, cancel_on_abandon=True)
    assert _plan_outbound(None, {}) == _OutboundPlan(metadata=None, cancel_on_abandon=True)


@pytest.mark.anyio
async def test_send_raw_request_projects_opts_headers_onto_message_metadata():
    """`opts["headers"]` alone yields `ClientMessageMetadata(headers=...)` on the outbound `SessionMessage`
    (SDK-defined: the headers sidecar is the path the session uses to reach the transport)."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)

            async def caller() -> None:
                await client.send_raw_request("tools/list", None, {"headers": {"x-test": "v"}})

            tg.start_soon(caller)
            with anyio.fail_after(5):
                outbound = await c2s_recv.receive()
            assert isinstance(outbound, SessionMessage)
            assert isinstance(outbound.message, JSONRPCRequest)
            assert isinstance(outbound.metadata, ClientMessageMetadata)
            assert outbound.metadata.headers == {"x-test": "v"}
            assert outbound.metadata.resumption_token is None
            await s2c_send.send(
                SessionMessage(message=JSONRPCResponse(jsonrpc="2.0", id=outbound.message.id, result={}))
            )
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_response_with_string_id_correlates_to_int_keyed_pending_request():
    """A peer that echoes the request ID as a JSON string still resolves the waiter."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            with anyio.fail_after(5):

                async def respond_stringly() -> None:
                    out = await c2s_recv.receive()
                    assert isinstance(out, SessionMessage)
                    assert isinstance(out.message, JSONRPCRequest)
                    rid = out.message.id
                    assert isinstance(rid, int)
                    await s2c_send.send(
                        SessionMessage(message=JSONRPCResponse(jsonrpc="2.0", id=str(rid), result={"ok": True}))
                    )

                tg.start_soon(respond_stringly)
                result = await client.send_raw_request("ping", None)
                assert result == {"ok": True}
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_error_response_with_string_id_correlates_to_int_keyed_pending_request():
    """A JSONRPCError echoing the request ID as a JSON string still resolves the waiter (same `_coerce_id` path)."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            with anyio.fail_after(5):

                async def reject_stringly() -> None:
                    out = await c2s_recv.receive()
                    assert isinstance(out, SessionMessage)
                    assert isinstance(out.message, JSONRPCRequest)
                    rid = out.message.id
                    assert isinstance(rid, int)
                    await s2c_send.send(
                        SessionMessage(
                            message=JSONRPCError(
                                jsonrpc="2.0", id=str(rid), error=ErrorData(code=INVALID_PARAMS, message="bad cursor")
                            )
                        )
                    )

                tg.start_soon(reject_stringly)
                with pytest.raises(MCPError) as exc:
                    await client.send_raw_request("ping", None)
                assert exc.value.error.code == INVALID_PARAMS
                assert exc.value.error.message == "bad cursor"  # the peer's error, passed through
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_progress_with_string_token_reaches_callback_for_int_keyed_request():
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())
    seen: list[float] = []
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            with anyio.fail_after(5):

                async def respond_with_string_token_progress() -> None:
                    out = await c2s_recv.receive()
                    assert isinstance(out, SessionMessage)
                    assert isinstance(out.message, JSONRPCRequest)
                    rid = out.message.id
                    assert isinstance(rid, int)
                    await s2c_send.send(
                        SessionMessage(
                            message=JSONRPCNotification(
                                jsonrpc="2.0",
                                method="notifications/progress",
                                params={"progressToken": str(rid), "progress": 0.5},
                            )
                        )
                    )
                    await s2c_send.send(
                        SessionMessage(message=JSONRPCResponse(jsonrpc="2.0", id=rid, result={"ok": True}))
                    )

                async def on_progress(progress: float, total: float | None, message: str | None) -> None:
                    seen.append(progress)

                tg.start_soon(respond_with_string_token_progress)
                result = await client.send_raw_request("ping", None, {"on_progress": on_progress})
                assert result == {"ok": True}
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
    assert seen == [0.5]


def test_coerce_id_passes_through_non_numeric_string_and_int():
    assert _coerce_id("7") == 7
    assert _coerce_id("not-an-int") == "not-an-int"
    assert _coerce_id(42) == 42


@pytest.mark.anyio
async def test_jsonrpc_error_response_with_null_id_is_dropped():
    """Parse-error responses (id=null) have no waiter; they're dropped and the read loop stays healthy."""
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
            with anyio.fail_after(5):
                # Ordered stream: this round-trip completing proves the null-id error was consumed.
                async def respond() -> None:
                    out = await c2s_recv.receive()
                    assert isinstance(out, SessionMessage)
                    assert isinstance(out.message, JSONRPCRequest)
                    await s2c_send.send(
                        SessionMessage(message=JSONRPCResponse(jsonrpc="2.0", id=out.message.id, result={"ok": True}))
                    )

                tg.start_soon(respond)
                assert await client.send_raw_request("ping", None) == {"ok": True}
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_notify_without_params_omits_params_key_on_the_wire():
    """JSON-RPC 2.0 forbids `params: null`: `notify` leaves `params` unset (transports use `exclude_unset=True`)."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    d: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    try:
        await d.notify("notifications/tools/list_changed", None)
        await d.notify("notifications/message", {"level": "info"})
        bare = c2s_recv.receive_nowait()
        with_params = c2s_recv.receive_nowait()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
    assert isinstance(bare, SessionMessage)
    wire = json.loads(bare.message.model_dump_json(by_alias=True, exclude_unset=True))
    assert wire == {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
    assert isinstance(with_params, SessionMessage)
    wire = json.loads(with_params.message.model_dump_json(by_alias=True, exclude_unset=True))
    assert wire == {"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info"}}


@pytest.mark.anyio
async def test_transport_builder_exception_on_request_is_answered_with_internal_error():
    """A raising builder costs only the one request, not the connection."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    calls = 0

    def builder(_meta: MessageMetadata) -> TransportContext:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("builder boom")
        return TransportContext(kind="jsonrpc", can_send_request=True)

    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send, transport_builder=builder)
    on_request, on_notify = echo_handlers(Recorder())
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, on_notify)
            await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="t", params=None)))
            with anyio.fail_after(5):
                resp = await s2c_recv.receive()
            assert isinstance(resp, SessionMessage)
            assert isinstance(resp.message, JSONRPCError)
            assert resp.message.id == 1
            assert resp.message.error == ErrorData(code=INTERNAL_ERROR, message="transport context unavailable")
            # The dispatcher stays healthy: the next request is served normally.
            await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=2, method="t", params=None)))
            with anyio.fail_after(5):
                resp2 = await s2c_recv.receive()
            assert isinstance(resp2, SessionMessage)
            assert isinstance(resp2.message, JSONRPCResponse)
            assert resp2.message.id == 2
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_transport_builder_exception_on_notification_drops_only_that_notification():
    """A raising builder drops the one notification; the read loop survives."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    calls = 0

    def builder(_meta: MessageMetadata) -> TransportContext:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("builder boom")
        return TransportContext(kind="jsonrpc", can_send_request=True)

    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send, transport_builder=builder)
    rec = Recorder()
    on_request, on_notify = echo_handlers(rec)
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, on_notify)
            await c2s_send.send(
                SessionMessage(message=JSONRPCNotification(jsonrpc="2.0", method="notifications/x", params=None))
            )
            await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=1, method="t", params=None)))
            with anyio.fail_after(5):
                resp = await s2c_recv.receive()
            assert isinstance(resp, SessionMessage)
            assert isinstance(resp.message, JSONRPCResponse)
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
    assert rec.notifications == []  # the notification never reached on_notify


@pytest.mark.anyio
async def test_cancelled_with_bool_request_id_does_not_cancel_request_one():
    """`int()` match patterns accept bool, and `True == 1` would alias the
    `_in_flight` lookup to request id 1; the bool guard must reject it."""
    handler_started = anyio.Event()
    handler_exited = anyio.Event()

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        handler_started.set()
        try:
            await anyio.sleep_forever()
        finally:
            handler_exited.set()
        raise NotImplementedError

    async with running_pair(jsonrpc_pair, server_on_request=server_on_request) as (client, _server, _crec, srec):
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch

                async def call() -> None:
                    with pytest.raises(MCPError):
                        await client.send_raw_request("slow", None)

                tg.start_soon(call)
                await handler_started.wait()
                await client.notify("notifications/cancelled", {"requestId": True})
                # Once the teed notification is observed, the correlation arm has already run.
                await srec.notified.wait()
                assert not handler_exited.is_set()
                await client.notify("notifications/cancelled", {"requestId": 1})
                await handler_exited.wait()


@pytest.mark.anyio
async def test_progress_with_bool_token_or_bool_progress_does_not_fire_callback():
    """Bool `progressToken`/`progress` values are malformed; the callback must
    not fire for the unrelated request keyed by id 1 (`True == 1`)."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send)
    on_request, on_notify = echo_handlers(Recorder())
    seen: list[float] = []
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(client.run, on_request, on_notify)
            with anyio.fail_after(5):

                async def respond_with_malformed_then_valid_progress() -> None:
                    out = await c2s_recv.receive()
                    assert isinstance(out, SessionMessage)
                    assert isinstance(out.message, JSONRPCRequest)
                    rid = out.message.id
                    for params in (
                        {"progressToken": True, "progress": 0.1},  # bool token
                        {"progressToken": rid, "progress": True},  # bool progress
                        {"progressToken": rid, "progress": 0.5},  # valid
                    ):
                        await s2c_send.send(
                            SessionMessage(
                                message=JSONRPCNotification(
                                    jsonrpc="2.0", method="notifications/progress", params=params
                                )
                            )
                        )
                    await s2c_send.send(
                        SessionMessage(message=JSONRPCResponse(jsonrpc="2.0", id=rid, result={"ok": True}))
                    )

                async def on_progress(progress: float, total: float | None, message: str | None) -> None:
                    seen.append(progress)

                tg.start_soon(respond_with_malformed_then_valid_progress)
                result = await client.send_raw_request("ping", None, {"on_progress": on_progress})
                assert result == {"ok": True}
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()
    assert seen == [0.5]  # only the well-formed progress fired the callback


@pytest.mark.anyio
async def test_request_with_bool_meta_progress_token_is_not_adopted():
    """A bool `_meta.progressToken` is malformed: `ctx.progress()` must be a no-op, not emit `progressToken: true`."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send)

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        await ctx.progress(0.5)
        return {"ok": True}

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, on_notify)
            await c2s_send.send(
                SessionMessage(
                    message=JSONRPCRequest(jsonrpc="2.0", id=1, method="t", params={"_meta": {"progressToken": True}})
                )
            )
            with anyio.fail_after(5):
                first = await s2c_recv.receive()
            # No progress notification was emitted; the first wire message is the response.
            assert isinstance(first, SessionMessage)
            assert isinstance(first.message, JSONRPCResponse)
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("request_id", "cancel_id"),
    [(7, "7"), ("9", 9)],
    ids=["string-cancel-for-int-request", "int-cancel-for-string-request"],
)
async def test_cancelled_correlates_across_string_and_int_request_id_forms(request_id: RequestId, cancel_id: object):
    """A peer that stringifies the id between request and cancel still cancels (same `_coerce_id` path)."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send)

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        await anyio.sleep_forever()
        raise NotImplementedError

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        pass

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, on_notify)
            await c2s_send.send(
                SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=request_id, method="t", params=None))
            )
            await c2s_send.send(
                SessionMessage(
                    message=JSONRPCNotification(
                        jsonrpc="2.0", method="notifications/cancelled", params={"requestId": cancel_id}
                    )
                )
            )
            with anyio.fail_after(5):
                resp = await s2c_recv.receive()
            assert isinstance(resp, SessionMessage)
            assert isinstance(resp.message, JSONRPCError)
            assert resp.message.id == request_id  # response echoes the peer's id form verbatim
            assert resp.message.error == ErrorData(code=0, message="Request cancelled")
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_completed_handler_does_not_evict_reused_request_id_from_in_flight():
    """A second request reusing an id while the first handler is parked in its response write
    keeps its own `_in_flight` entry (a post-write pop would evict it and break peer-cancellation)."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    # buffer=0: the first handler's response write parks until the test receives.
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send)
    calls = 0
    second_started = anyio.Event()
    second_exited = anyio.Event()

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"first": True}
        second_started.set()
        try:
            await anyio.sleep_forever()
        finally:
            second_exited.set()
        raise NotImplementedError

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        pass

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, on_notify)
            with anyio.fail_after(5):
                await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=7, method="a")))
                # First handler is now parked in `_write_result`; reuse its id.
                await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=7, method="b")))
                await second_started.wait()
                resp1 = await s2c_recv.receive()
                assert isinstance(resp1, SessionMessage)
                assert isinstance(resp1.message, JSONRPCResponse)
                assert resp1.message.result == {"first": True}
                # Let the first handler task run to completion past the write.
                await anyio.wait_all_tasks_blocked()
                assert 7 in server._in_flight  # pyright: ignore[reportPrivateUsage]
                # The surviving entry must still be cancellable.
                await c2s_send.send(
                    SessionMessage(
                        message=JSONRPCNotification(
                            jsonrpc="2.0", method="notifications/cancelled", params={"requestId": 7}
                        )
                    )
                )
                resp2 = await s2c_recv.receive()
                assert isinstance(resp2, SessionMessage)
                assert isinstance(resp2.message, JSONRPCError)
                assert resp2.message.error == ErrorData(code=0, message="Request cancelled")
                assert second_exited.is_set()
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


@pytest.mark.anyio
async def test_duplicate_request_id_completion_of_first_handler_keeps_second_cancellable():
    """A duplicate inbound id overwrites `_in_flight` (parity with v1/TS); the identity-guarded pop
    keeps the first handler's completion from evicting the second's entry and breaking its cancellation."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send)
    first_started = anyio.Event()
    release_first = anyio.Event()
    second_started = anyio.Event()
    second_exited = anyio.Event()

    async def on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        if method == "first":
            first_started.set()
            await release_first.wait()
            return {"first": True}
        second_started.set()
        try:
            await anyio.sleep_forever()
        finally:
            second_exited.set()
        raise NotImplementedError

    async def on_notify(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> None:
        pass  # the cancelled notification is teed here; nothing to observe

    try:
        async with anyio.create_task_group() as tg:
            await tg.start(server.run, on_request, on_notify)
            with anyio.fail_after(5):
                await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=7, method="first")))
                await first_started.wait()
                # Duplicate id: the table entry now belongs to the second request.
                await c2s_send.send(SessionMessage(message=JSONRPCRequest(jsonrpc="2.0", id=7, method="second")))
                await second_started.wait()
                release_first.set()
                resp1 = await s2c_recv.receive()
                assert isinstance(resp1, SessionMessage)
                assert isinstance(resp1.message, JSONRPCResponse)
                assert resp1.message.result == {"first": True}
                # Let the first handler task run past its pop entirely.
                await anyio.wait_all_tasks_blocked()
                assert 7 in server._in_flight  # pyright: ignore[reportPrivateUsage]
                # The surviving entry must still be cancellable by the peer.
                await c2s_send.send(
                    SessionMessage(
                        message=JSONRPCNotification(
                            jsonrpc="2.0", method="notifications/cancelled", params={"requestId": 7}
                        )
                    )
                )
                resp2 = await s2c_recv.receive()
                assert isinstance(resp2, SessionMessage)
                assert isinstance(resp2.message, JSONRPCError)
                assert resp2.message.error == ErrorData(code=0, message="Request cancelled")
                assert second_exited.is_set()
            tg.cancel_scope.cancel()
    finally:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()


def test_plan_outbound_with_related_request_id_drops_resumption_hints_but_keeps_abandon_cancel(
    caplog: pytest.LogCaptureFixture,
):
    """`related_request_id` wins the metadata slot; dropped hints don't suppress the abandon cancel."""
    with caplog.at_level(logging.DEBUG, logger="mcp.shared.jsonrpc_dispatcher"):
        plan = _plan_outbound(7, {"resumption_token": "abc"})
    assert isinstance(plan.metadata, ServerMessageMetadata)
    assert plan.metadata.related_request_id == 7
    assert plan.cancel_on_abandon is True
    assert "dropping resumption hints" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="mcp.shared.jsonrpc_dispatcher"):
        plan = _plan_outbound(7, {"timeout": 1.0})
    assert isinstance(plan.metadata, ServerMessageMetadata)
    assert "dropping resumption hints" not in caplog.text


@pytest.mark.anyio
async def test_server_middleware_observes_cancelled_notification():
    """`Server.middleware` wraps every inbound notification, including `notifications/cancelled`
    (the dispatcher applies the cancellation itself, then forwards the notification)."""
    handler_started = anyio.Event()
    cancel_observed = anyio.Event()
    observed: list[tuple[str, dict[str, Any]]] = []
    request_id: RequestId | None = None

    async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        nonlocal request_id
        request_id = ctx.request_id
        handler_started.set()
        await anyio.sleep_forever()
        raise NotImplementedError

    async def observe(ctx: Any, call_next: Any) -> Any:
        if ctx.method == "notifications/cancelled":
            observed.append((ctx.method, dict(ctx.params or {})))
            cancel_observed.set()
        return await call_next(ctx)

    server = Server("test-server", on_call_tool=handle_call_tool)
    server.middleware.append(observe)

    async with Client(server, mode="legacy") as client:
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch

                async def call() -> None:
                    with pytest.raises(MCPError):
                        await client.session.send_request(
                            CallToolRequest(params=CallToolRequestParams(name="t", arguments={})),
                            CallToolResult,
                        )

                tg.start_soon(call)
                await handler_started.wait()
                assert request_id is not None
                await client.session.send_notification(
                    CancelledNotification(
                        params=CancelledNotificationParams(request_id=request_id, reason="user clicked stop")
                    )
                )
                await cancel_observed.wait()
    assert len(observed) == 1
    assert observed[0][0] == "notifications/cancelled"
    assert observed[0][1]["requestId"] == request_id
    assert observed[0][1]["reason"] == "user clicked stop"
