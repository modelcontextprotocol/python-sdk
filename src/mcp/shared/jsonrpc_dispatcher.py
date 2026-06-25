"""JSON-RPC `Dispatcher` over the `SessionMessage` stream contract all transports speak.

Owns request-id correlation, the receive loop, per-request task isolation,
cancellation/progress wiring, and the single exception-to-wire boundary;
methods and params are otherwise opaque strings and dicts.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Generic, Literal, cast

import anyio
import anyio.abc
import anyio.lowlevel
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp_types import (
    CONNECTION_CLOSED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    REQUEST_TIMEOUT,
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ProgressToken,
    RequestId,
)
from opentelemetry.trace import SpanKind
from pydantic import ValidationError
from typing_extensions import TypeVar

from mcp.shared._compat import resync_tracer
from mcp.shared._otel import inject_trace_context, otel_span
from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.dispatcher import CallOptions, DispatchContext, Dispatcher, OnNotify, OnRequest, ProgressFnT
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.shared.message import (
    ClientMessageMetadata,
    MessageMetadata,
    ServerMessageMetadata,
    SessionMessage,
)
from mcp.shared.transport_context import TransportContext

__all__ = ["JSONRPCDispatcher", "handler_exception_to_error_data"]

logger = logging.getLogger(__name__)

_ABANDON_WRITE_TIMEOUT: float = 5
"""Bound for courtesy-cancel writes on the abandon paths; the caller-cancel
arm shields its write, so a wedged transport would otherwise hang it uncancellably."""

_SHUTDOWN_WRITE_TIMEOUT: float = 1
"""Tighter bound for the shutdown-arm error write so a wedged transport can't hold session close."""

TransportT = TypeVar("TransportT", bound=TransportContext, default=TransportContext)

PeerCancelMode = Literal["interrupt", "signal"]
"""How `notifications/cancelled` is applied: `"interrupt"` (default) cancels
the handler's scope; `"signal"` only sets `ctx.cancel_requested`."""


def handler_exception_to_error_data(exc: BaseException) -> ErrorData | None:
    """Map a handler-raised exception to its wire `ErrorData`.

    The two rungs every dispatcher shares: an `MCPError` carries its own
    `ErrorData`; a pydantic `ValidationError` is the spec's INVALID_PARAMS
    with empty ``data`` (no pydantic text on the wire). Returns ``None`` for
    any other exception so each caller applies its own catch-all -
    `JSONRPCDispatcher` currently pins ``code=0`` for v1 compat,
    the modern HTTP entry uses `INTERNAL_ERROR`.
    """
    if isinstance(exc, MCPError):
        return exc.error
    if isinstance(exc, ValidationError):
        return ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")
    return None


def _coerce_id(request_id: RequestId) -> RequestId:
    """Coerce a stringified int request ID back to int so a peer-echoed ID still correlates (matches the TS SDK)."""
    if isinstance(request_id, str):
        try:
            return int(request_id)
        except ValueError:
            pass
    return request_id


@dataclass(slots=True)
class _Pending:
    """An outbound request awaiting its response."""

    send: MemoryObjectSendStream[dict[str, Any] | ErrorData]
    receive: MemoryObjectReceiveStream[dict[str, Any] | ErrorData]
    on_progress: ProgressFnT | None = None


@dataclass(slots=True)
class _InFlight(Generic[TransportT]):
    """An inbound request currently being handled."""

    scope: anyio.CancelScope
    dctx: _JSONRPCDispatchContext[TransportT]


@dataclass
class _JSONRPCDispatchContext(Generic[TransportT]):
    """Concrete `DispatchContext` produced for each inbound JSON-RPC message."""

    transport: TransportT
    _dispatcher: JSONRPCDispatcher[TransportT]
    _request_id: RequestId | None
    message_metadata: MessageMetadata = None  # TODO(maxisbey): remove for Context rework
    """Transport-attached `SessionMessage.metadata` that the server lifts onto its request context."""
    _progress_token: ProgressToken | None = None
    _closed: bool = False
    cancel_requested: anyio.Event = field(default_factory=anyio.Event)

    @property
    def request_id(self) -> RequestId | None:
        return self._request_id

    @property
    def can_send_request(self) -> bool:
        return self.transport.can_send_request and not self._closed

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        if self._closed:
            logger.debug("dropped %s: dispatch context closed", method)
            return
        await self._dispatcher.notify(method, params, opts, _related_request_id=self._request_id)

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        if not self.can_send_request:
            raise NoBackChannelError(method)
        return await self._dispatcher.send_raw_request(method, params, opts, _related_request_id=self._request_id)

    async def progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        if self._progress_token is None:
            return
        params: dict[str, Any] = {"progressToken": self._progress_token, "progress": progress}
        if total is not None:
            params["total"] = total
        if message is not None:
            params["message"] = message
        await self.notify("notifications/progress", params)

    def close(self) -> None:
        self._closed = True


def _default_transport_builder(_meta: MessageMetadata) -> TransportContext:
    return TransportContext(kind="jsonrpc", can_send_request=True)


def _shielded_progress(fn: ProgressFnT) -> ProgressFnT:
    """Wrap a user progress callback so an exception can't cancel the dispatcher's task group."""

    async def _wrapped(progress: float, total: float | None, message: str | None) -> None:
        try:
            await fn(progress, total, message)
        except Exception:
            logger.exception("progress callback raised")

    return _wrapped


def _contained_notify(fn: OnNotify) -> OnNotify:
    """Wrap a notification handler so it can't crash the dispatcher (same boundary as `_shielded_progress`)."""

    async def _wrapped(dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None) -> None:
        try:
            await fn(dctx, method, params)
        except Exception:
            logger.exception("notification handler for %r raised", method)

    return _wrapped


@dataclass(slots=True, frozen=True)
class _OutboundPlan:
    """Outbound metadata plus whether abandoning the request sends a courtesy `notifications/cancelled`."""

    metadata: MessageMetadata
    cancel_on_abandon: bool


def _plan_outbound(related_request_id: RequestId | None, opts: CallOptions | None) -> _OutboundPlan:
    """Choose the outbound `SessionMessage.metadata` and the abandon-cancellation policy.

    `related_request_id` wins over resumption hints (they are dropped). Only
    hints that actually reach the transport suppress the courtesy cancel - a
    request that is neither resumable nor cancelled would leak the peer's work.
    """
    opts = opts or {}
    cancel_on_abandon = opts.get("cancel_on_abandon", True)
    token = opts.get("resumption_token")
    on_token = opts.get("on_resumption_token")
    headers = opts.get("headers")
    if related_request_id is not None:
        if token is not None or on_token is not None:
            logger.debug(
                "dropping resumption hints: related_request_id %r takes precedence on metadata", related_request_id
            )
        return _OutboundPlan(ServerMessageMetadata(related_request_id=related_request_id), cancel_on_abandon)
    if token is not None or on_token is not None:
        return _OutboundPlan(
            ClientMessageMetadata(resumption_token=token, on_resumption_token_update=on_token, headers=headers),
            cancel_on_abandon=False,
        )
    if headers:
        return _OutboundPlan(ClientMessageMetadata(headers=headers), cancel_on_abandon)
    return _OutboundPlan(None, cancel_on_abandon)


class JSONRPCDispatcher(Dispatcher[TransportT]):
    """`Dispatcher` over the `SessionMessage` stream contract.

    Explicit Protocol base so pyright checks conformance at the class definition.
    """

    def __init__(
        self,
        read_stream: ReadStream[SessionMessage | Exception],
        write_stream: WriteStream[SessionMessage],
        *,
        transport_builder: Callable[[MessageMetadata], TransportT] | None = None,
        peer_cancel_mode: PeerCancelMode = "interrupt",
        raise_handler_exceptions: bool = False,
        inline_methods: frozenset[str] = frozenset(),
        on_stream_exception: Callable[[Exception], Awaitable[None]] | None = None,
    ) -> None:
        """Wire a dispatcher over a transport's `SessionMessage` stream pair.

        Args:
            transport_builder: Builds each message's `TransportContext` from
                its `SessionMessage.metadata`.
            raise_handler_exceptions: Re-raise handler exceptions out of
                `run()` after the error response is written.
            inline_methods: Methods awaited in the read loop before the next
                message is dequeued (e.g. `initialize`); an inline handler
                that awaits the peer deadlocks the parked loop.
            on_stream_exception: Observer for `Exception` items on the read
                stream; without it they are debug-logged and dropped. Awaited
                inline in the read loop, so a slow observer stalls dispatch.
        """
        self._read_stream = read_stream
        self._write_stream = write_stream
        # With transport_builder omitted, TransportT defaults to
        # TransportContext; pyright can't connect the two, hence the cast.
        self._transport_builder = cast(
            "Callable[[MessageMetadata], TransportT]",
            transport_builder or _default_transport_builder,
        )
        self._peer_cancel_mode: PeerCancelMode = peer_cancel_mode
        self._raise_handler_exceptions = raise_handler_exceptions
        self._inline_methods = inline_methods
        self.on_stream_exception = on_stream_exception
        """Observer for ``Exception`` items on the read stream. Mutable so a session can
        bind it after the dispatcher is built (e.g. ``ClientSession`` routing into
        ``message_handler``); only consulted inside ``run()`` so pre-enter assignment is safe."""

        self._next_id = 0
        self._pending: dict[RequestId, _Pending] = {}
        self._in_flight: dict[RequestId, _InFlight[TransportT]] = {}
        self._tg: anyio.abc.TaskGroup | None = None
        self._running = False
        self._closed = False

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
        *,
        _related_request_id: RequestId | None = None,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and await its response.

        `_related_request_id` is set only by `_JSONRPCDispatchContext` so that
        mid-handler requests route onto the inbound request's SSE stream.

        Raises:
            MCPError: Peer error response; `REQUEST_TIMEOUT` if
                `opts["timeout"]` elapsed; `CONNECTION_CLOSED` if the
                transport closed or the dispatcher shut down.
            RuntimeError: Called before `run()`.
        """
        # Post-close sends get the same CONNECTION_CLOSED contract as in-flight waiters.
        if self._closed:
            raise MCPError(code=CONNECTION_CLOSED, message="Connection closed")
        if not self._running:
            raise RuntimeError("JSONRPCDispatcher.send_raw_request called before run()")
        opts = opts or {}
        request_id = self._allocate_id()
        out_params = dict(params) if params is not None else {}
        out_meta = dict(out_params.get("_meta") or {})
        on_progress = opts.get("on_progress")
        if on_progress is not None:
            # The request id doubles as the progress token, so `_pending[token]` finds `on_progress` directly.
            out_meta["progressToken"] = request_id
        out_params["_meta"] = out_meta

        # buffer=1: a close signal can arrive before the waiter parks in receive();
        # a WouldBlock later just means the waiter already has its one outcome.
        send, receive = anyio.create_memory_object_stream[dict[str, Any] | ErrorData](1)
        pending = _Pending(send=send, receive=receive, on_progress=on_progress)
        self._pending[request_id] = pending

        plan = _plan_outbound(_related_request_id, opts)
        # Spec MUST: only previously-issued requests may be cancelled. A write
        # interrupted by cancellation may still have delivered (a memory-stream
        # send can hand its item to the receiver and still raise), so a started
        # write counts as issued: the peer ignores a cancel for an id it never
        # saw, while skipping it would leak a delivered request's handler.
        request_write_started = False
        timeout_armed = False

        target = out_params.get("name")
        span_name = f"MCP send {method}{f' {target}' if isinstance(target, str) else ''}"
        # TODO(maxisbey): move the otel span + inject into an outbound
        # middleware once that seam exists; the dispatcher should not own otel.
        try:
            with otel_span(
                span_name,
                kind=SpanKind.CLIENT,
                attributes={"mcp.method.name": method, "jsonrpc.request.id": str(request_id)},
            ):
                # SEP-414: inject W3C trace context; `_meta` stays on the wire even with a no-op tracer.
                inject_trace_context(out_meta)
                msg = JSONRPCRequest(jsonrpc="2.0", id=request_id, method=method, params=out_params)
                # Surface a pre-existing cancellation while the request provably
                # never started; past this point a cancelled write counts as issued.
                await anyio.lowlevel.checkpoint_if_cancelled()
                request_write_started = True
                try:
                    await self._write(msg, plan.metadata)
                except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                    # Transport tore down before run() noticed EOF; surface the documented contract.
                    raise MCPError(code=CONNECTION_CLOSED, message="Connection closed") from None
                with anyio.fail_after(opts.get("timeout")):
                    timeout_armed = True
                    outcome = await receive.receive()
        except TimeoutError:
            if not timeout_armed:
                # `fail_after` arms only after the write, so this TimeoutError is the
                # transport's own bounded send() failing - a transport error, not
                # `opts["timeout"]` elapsing. Propagate it raw (v1 kept the write
                # outside the timeout-catching try and did the same).
                raise
            # Courtesy cancel (spec-recommended, new vs v1) so the peer stops work;
            # unshielded so an outer caller cancellation can still interrupt the write.
            if plan.cancel_on_abandon:
                await self._final_write(
                    partial(
                        self._cancel_outbound,
                        request_id,
                        f"timed out after {opts.get('timeout')}s",
                        _related_request_id,
                    ),
                    shield=False,
                    timeout=_ABANDON_WRITE_TIMEOUT,
                    describe=f"courtesy cancel for timed-out request {request_id!r}",
                )
            raise MCPError(code=REQUEST_TIMEOUT, message=f"Request {method!r} timed out") from None
        except anyio.get_cancelled_exc_class():
            # Caller cancelled: bare awaits re-raise here, so the shielded helper
            # lets the courtesy cancel go out before we propagate.
            if plan.cancel_on_abandon and request_write_started:
                await self._final_write(
                    partial(self._cancel_outbound, request_id, "caller cancelled", _related_request_id),
                    shield=True,
                    timeout=_ABANDON_WRITE_TIMEOUT,
                    describe=f"courtesy cancel for caller-cancelled request {request_id!r}",
                )
            raise
        finally:
            # Remove the waiter on every path so a late response is dropped, not leaked.
            self._pending.pop(request_id, None)
            send.close()
            receive.close()

        if isinstance(outcome, ErrorData):
            raise MCPError(code=outcome.code, message=outcome.message, data=outcome.data)
        return outcome

    async def notify(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
        *,
        _related_request_id: RequestId | None = None,
    ) -> None:
        """Send a fire-and-forget notification.

        Fire-and-forget all the way: a post-close send or a write onto a
        torn-down transport drops the notification with a debug log instead
        of raising (same policy as the response writes and `ctx.notify`).
        """
        if self._closed:
            logger.debug("dropped %s: dispatcher closed", method)
            return
        # Leave `params` unset when None: with `exclude_unset=True` an explicit
        # None would serialize as `"params": null`, which JSON-RPC 2.0 forbids.
        if params is not None:
            msg = JSONRPCNotification(jsonrpc="2.0", method=method, params=dict(params))
        else:
            msg = JSONRPCNotification(jsonrpc="2.0", method=method)
        try:
            await self._write(msg, _plan_outbound(_related_request_id, opts).metadata)
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            # Transport tore down before run() noticed EOF.
            logger.debug("dropped %s: write stream closed", method)

    async def run(
        self,
        on_request: OnRequest,
        on_notify: OnNotify,
        *,
        task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        """Drive the receive loop until the read stream closes.

        `task_status.started()` fires once `send_raw_request` is usable.
        Single-shot: once the loop ends the dispatcher stays closed and cannot be restarted.
        """
        try:
            # LIFO exits: the write stream closes only after the task-group join, so teardown writes still land.
            async with self._write_stream:
                async with anyio.create_task_group() as tg:
                    self._tg = tg
                    self._running = True
                    task_status.started()
                    try:
                        async with self._read_stream:
                            try:
                                async for item in self._read_stream:
                                    # Duck-typed: only `ContextReceiveStream` carries the
                                    # sender's per-message contextvars snapshot.
                                    sender_ctx: contextvars.Context | None = getattr(
                                        self._read_stream, "last_context", None
                                    )
                                    await self._dispatch(item, on_request, on_notify, sender_ctx)
                            except anyio.ClosedResourceError:
                                # Receive end closed under us (stateless SHTTP teardown); same as EOF.
                                logger.debug("read stream closed by transport; treating as EOF")
                        # EOF: wake blocked `send_raw_request` waiters with CONNECTION_CLOSED.
                        self._running = False
                        self._closed = True
                        self._fan_out_closed()
                    finally:
                        # Cancel in-flight handlers; otherwise the task-group join
                        # waits on handlers whose callers are already gone.
                        tg.cancel_scope.cancel()
        finally:
            # Covers cancel/crash paths that skip the inline fan-out; idempotent.
            self._running = False
            self._closed = True
            self._tg = None
            self._fan_out_closed()
            await resync_tracer()

    async def _dispatch(
        self,
        item: SessionMessage | Exception,
        on_request: OnRequest,
        on_notify: OnNotify,
        sender_ctx: contextvars.Context | None,
    ) -> None:
        """Route one inbound item.

        Only `inline_methods` requests and the `on_stream_exception` observer
        are awaited; any other `await` would head-of-line block the read loop.
        """
        if isinstance(item, Exception):
            if self.on_stream_exception is None:
                logger.debug("transport yielded exception: %r", item)
                return
            try:
                await self.on_stream_exception(item)
            except Exception:
                logger.exception("on_stream_exception observer raised")
            return
        metadata = item.metadata
        msg = item.message
        match msg:
            case JSONRPCRequest():
                await self._dispatch_request(msg, metadata, on_request, sender_ctx)
            case JSONRPCNotification():
                self._dispatch_notification(msg, metadata, on_notify, sender_ctx)
            case JSONRPCResponse():
                self._resolve_pending(msg.id, msg.result)
            case JSONRPCError():  # pragma: no branch
                # Exhaustive over JSONRPCMessage, so the no-match arc is unreachable.
                self._resolve_pending(msg.id, msg.error)

    async def _dispatch_request(
        self,
        req: JSONRPCRequest,
        metadata: MessageMetadata,
        on_request: OnRequest,
        sender_ctx: contextvars.Context | None,
    ) -> None:
        progress_token: ProgressToken | None
        match req.params:
            # bool subclasses int: without the guard True would alias request id 1.
            case {"_meta": {"progressToken": str() | int() as progress_token}} if not isinstance(progress_token, bool):
                pass
            case _:
                progress_token = None
        try:
            transport_ctx = self._transport_builder(metadata)
        except Exception:
            # A raising builder must cost only this message, not the connection.
            logger.exception("transport_builder raised; rejecting request %r", req.id)
            self._spawn(
                self._write_error,
                req.id,
                ErrorData(code=INTERNAL_ERROR, message="transport context unavailable"),
                sender_ctx=sender_ctx,
            )
            return
        dctx = _JSONRPCDispatchContext(
            transport=transport_ctx,
            _dispatcher=self,
            _request_id=req.id,
            message_metadata=metadata,
            _progress_token=progress_token,
        )
        scope = anyio.CancelScope()
        # TODO(maxisbey): duplicate ids blind-overwrite (v1/TS parity); revisit
        # rejecting with INVALID_REQUEST. Key coerced so a stringified
        # `notifications/cancelled` id still correlates.
        self._in_flight[_coerce_id(req.id)] = _InFlight(scope=scope, dctx=dctx)
        if req.method in self._inline_methods:
            # Spawn so `sender_ctx` applies, but park the read loop until the
            # handler returns - that's the inline ordering guarantee.
            done = anyio.Event()

            async def _run_inline() -> None:
                try:
                    await self._handle_request(req, dctx, scope, on_request)
                finally:
                    done.set()

            self._spawn(_run_inline, sender_ctx=sender_ctx)
            await done.wait()
        else:
            self._spawn(self._handle_request, req, dctx, scope, on_request, sender_ctx=sender_ctx)

    def _dispatch_notification(
        self,
        msg: JSONRPCNotification,
        metadata: MessageMetadata,
        on_notify: OnNotify,
        sender_ctx: contextvars.Context | None,
    ) -> None:
        """Route one inbound notification.

        `notifications/cancelled` and `notifications/progress` are intercepted
        here (they correlate against the `_in_flight`/`_pending` tables this
        layer owns) and still teed to `on_notify` afterwards.
        """
        if msg.method == "notifications/cancelled":
            match msg.params:
                # bool subclasses int: the guards keep True from aliasing request id 1.
                case {"requestId": str() | int() as rid} if (
                    not isinstance(rid, bool) and (in_flight := self._in_flight.get(_coerce_id(rid))) is not None
                ):
                    in_flight.dctx.cancel_requested.set()
                    if self._peer_cancel_mode == "interrupt":
                        in_flight.scope.cancel()
                case _:
                    pass
        elif msg.method == "notifications/progress":
            match msg.params:
                case {"progressToken": str() | int() as token, "progress": int() | float() as progress} if (
                    not isinstance(token, bool)
                    and not isinstance(progress, bool)
                    and (pending := self._pending.get(_coerce_id(token))) is not None
                    and pending.on_progress is not None
                ):
                    total = msg.params.get("total")
                    message = msg.params.get("message")
                    self._spawn(
                        _shielded_progress(pending.on_progress),
                        float(progress),
                        float(total) if isinstance(total, int | float) else None,
                        message if isinstance(message, str) else None,
                        sender_ctx=sender_ctx,
                    )
                case _:
                    pass
        try:
            transport_ctx = self._transport_builder(metadata)
        except Exception:
            # Same containment as `_dispatch_request`: drop the notification, keep the loop.
            logger.exception("transport_builder raised; dropping notification %r", msg.method)
            return
        dctx = _JSONRPCDispatchContext(
            transport=transport_ctx, _dispatcher=self, _request_id=None, message_metadata=metadata
        )
        self._spawn(_contained_notify(on_notify), dctx, msg.method, msg.params, sender_ctx=sender_ctx)

    def _resolve_pending(self, request_id: RequestId | None, outcome: dict[str, Any] | ErrorData) -> None:
        pending = self._pending.get(_coerce_id(request_id)) if request_id is not None else None
        if pending is None:
            logger.debug("dropping response for unknown/late request id %r", request_id)
            return
        try:
            pending.send.send_nowait(outcome)
        except (anyio.WouldBlock, anyio.BrokenResourceError, anyio.ClosedResourceError):
            logger.debug("waiter for request id %r already gone", request_id)

    def _spawn(
        self,
        fn: Callable[..., Awaitable[Any]],
        *args: object,
        sender_ctx: contextvars.Context | None,
    ) -> None:
        """Schedule `fn(*args)` in the run() task group, propagating the sender's contextvars.

        ASGI middleware (auth, OTel) sets contextvars on the task that wrote the
        message; `Context.run` makes the spawned handler inherit that context.
        """
        assert self._tg is not None
        if sender_ctx is not None:
            sender_ctx.run(self._tg.start_soon, fn, *args)
        else:
            self._tg.start_soon(fn, *args)

    def _fan_out_closed(self) -> None:
        """Wake every pending `send_raw_request` waiter with `CONNECTION_CLOSED`.

        Synchronous: callers may be inside a cancelled scope. Idempotent.
        """
        closed = ErrorData(code=CONNECTION_CLOSED, message="Connection closed")
        for pending in self._pending.values():
            try:
                pending.send.send_nowait(closed)
            except (anyio.WouldBlock, anyio.BrokenResourceError, anyio.ClosedResourceError):
                pass
        self._pending.clear()

    async def _handle_request(
        self,
        req: JSONRPCRequest,
        dctx: _JSONRPCDispatchContext[TransportT],
        scope: anyio.CancelScope,
        on_request: OnRequest,
    ) -> None:
        """Run `on_request` for one inbound request and write its response.

        The single exception-to-wire boundary: handler exceptions become `JSONRPCError` here.
        """
        answer_write_started = False
        try:
            with scope:
                try:
                    result = await on_request(dctx, req.method, req.params)
                finally:
                    # Close the back-channel and drop from `_in_flight`; no checkpoint
                    # since handler return, so a peer cancel can't interleave.
                    # Identity guard: don't evict a duplicate id's newer entry.
                    dctx.close()
                    key = _coerce_id(req.id)
                    if (entry := self._in_flight.get(key)) is not None and entry.dctx is dctx:
                        del self._in_flight[key]
                # A write interrupted by cancellation may still have delivered
                # (a memory-stream send can hand its item to the receiver and
                # still raise), so a started answer write counts as sent below:
                # peers drop late responses, while a second answer for one id
                # would break JSON-RPC.
                answer_write_started = True
                await self._write_result(req.id, result)
            if scope.cancelled_caught:
                # anyio absorbs the scope's own cancel at __exit__, and
                # `cancelled_caught` (unlike `cancel_called`) guarantees the
                # result write above did not happen - no double response.
                # TODO(L38): spec says SHOULD NOT respond after cancel;
                # the existing server always has, so match that for now.
                answer_write_started = True
                await self._write_error(req.id, ErrorData(code=0, message="Request cancelled"))
        except anyio.get_cancelled_exc_class():
            # Shutdown: answer the request so the peer isn't left waiting - unless
            # an answer write already started (it may have reached the transport;
            # prefer possibly-zero answers over possibly-two). The shielded helper
            # is needed because bare awaits re-raise here.
            if not answer_write_started:
                await self._final_write(
                    partial(self._write_error, req.id, ErrorData(code=CONNECTION_CLOSED, message="Connection closed")),
                    shield=True,
                    timeout=_SHUTDOWN_WRITE_TIMEOUT,
                    describe=f"shutdown error response for request {req.id!r}",
                )
            raise
        except Exception as e:
            error = handler_exception_to_error_data(e)
            if error is not None:
                await self._write_error(req.id, error)
            else:
                logger.exception("handler for %r raised", req.method)
                # TODO(L58): code=0 pins existing-server compat; JSON-RPC says
                # INTERNAL_ERROR. Revisit per the suite's divergence entry.
                await self._write_error(req.id, ErrorData(code=0, message=str(e)))
                if self._raise_handler_exceptions:
                    raise
        # No `_in_flight` pop here: the inner finally covers every path, and a late pop could evict a reused id.

    def _allocate_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def _write(self, message: JSONRPCMessage, metadata: MessageMetadata = None) -> None:
        await self._write_stream.send(SessionMessage(message=message, metadata=metadata))

    async def _write_result(self, request_id: RequestId, result: dict[str, Any]) -> None:
        try:
            await self._write(JSONRPCResponse(jsonrpc="2.0", id=request_id, result=result))
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            logger.debug("dropped result for %r: write stream closed", request_id)

    async def _write_error(self, request_id: RequestId, error: ErrorData) -> None:
        try:
            await self._write(JSONRPCError(jsonrpc="2.0", id=request_id, error=error))
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            logger.debug("dropped error for %r: write stream closed", request_id)

    async def _final_write(
        self,
        write: Callable[[], Awaitable[None]],
        *,
        shield: bool,
        timeout: float,
        describe: str,
    ) -> None:
        """Attempt one last write under the shared abandon/teardown policy.

        `shield=True` is for arms already inside a cancelled scope (a bare
        `await` would re-raise); the bound keeps a wedged transport write
        from becoming an uncancellable hang.
        """
        with anyio.move_on_after(timeout, shield=shield) as scope:
            await write()
        if scope.cancelled_caught:
            logger.warning("%s gave up: transport write blocked", describe)

    async def _cancel_outbound(self, request_id: RequestId, reason: str, related_request_id: RequestId | None) -> None:
        # Thread `related_request_id` so streamable HTTP routes the cancel onto
        # the request's own SSE stream instead of a possibly-absent GET stream.
        # `notify` swallows connection-state errors itself, so no guard here.
        await self.notify(
            "notifications/cancelled",
            {"requestId": request_id, "reason": reason},
            _related_request_id=related_request_id,
        )
