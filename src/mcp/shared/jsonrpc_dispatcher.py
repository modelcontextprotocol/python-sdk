"""JSON-RPC `Dispatcher` over the `SessionMessage` stream contract all transports speak.

Owns the receive loop and per-request task isolation over a duplex stream
pair; request-id correlation, cancellation/progress wiring, and the single
exception-to-wire boundary live in the shared `RequestCorrelator` so the
streamable-HTTP transport (which has no stream pair) applies the same
semantics. Methods and params are otherwise opaque strings and dicts.
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
from mcp_types import (
    INTERNAL_ERROR,
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ProgressToken,
    RequestId,
)
from typing_extensions import TypeVar

from mcp.shared._compat import resync_tracer
from mcp.shared._correlation import (
    InFlight,
    Outcome,
    Pending,
    RequestCorrelator,
    handler_exception_to_error_data,
)
from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.dispatcher import (
    CallOptions,
    DispatchContext,
    Dispatcher,
    OnNotify,
    OnNotifyIntercept,
    OnRequest,
    as_request_id,
    run_notify_intercept,
)
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.message import (
    ClientMessageMetadata,
    MessageMetadata,
    ServerMessageMetadata,
    SessionMessage,
)
from mcp.shared.transport_context import TransportContext

__all__ = [
    "JSONRPCDispatcher",
    "cancelled_request_id_from_params",
    "handler_exception_to_error_data",
    "progress_token_from_params",
]

logger = logging.getLogger(__name__)

TransportT = TypeVar("TransportT", bound=TransportContext, default=TransportContext)

PeerCancelMode = Literal["interrupt", "signal"]
"""How `notifications/cancelled` is applied: `"interrupt"` (default) cancels
the handler's scope; `"signal"` only sets `ctx.cancel_requested`."""

_Pending = Pending
"""Outbound-waiter record; owned by `RequestCorrelator` (aliased here for white-box tests)."""


def progress_token_from_params(params: Mapping[str, Any] | None) -> ProgressToken | None:
    """Read `params._meta.progressToken`; reject bool (bool subclasses int, so True would alias 1)."""
    match params:
        case {"_meta": {"progressToken": str() | int() as token}} if not isinstance(token, bool):
            return token
        case _:
            return None


def cancelled_request_id_from_params(params: Mapping[str, Any] | None) -> RequestId | None:
    """Read `params.requestId` from a `notifications/cancelled` (`as_request_id` shape rules)."""
    return as_request_id((params or {}).get("requestId"))


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


def _contained_notify(fn: OnNotify) -> OnNotify:
    """Wrap a notification handler so it can't crash the dispatcher's task group."""

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

        # The correlation kernel owns the pending/in-flight tables; the
        # aliases keep the historical private names white-box tests read.
        self._corr: RequestCorrelator[_JSONRPCDispatchContext[TransportT]] = RequestCorrelator()
        self._pending: dict[RequestId, Pending] = self._corr.pending
        self._in_flight: dict[RequestId, InFlight[_JSONRPCDispatchContext[TransportT]]] = self._corr.in_flight
        self._on_notify_intercept: OnNotifyIntercept | None = None
        self._tg: anyio.abc.TaskGroup | None = None
        self._running = False

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
        # Post-close sends get the same CONNECTION_CLOSED contract as in-flight
        # waiters (raised by the correlator); only a never-run dispatcher is a usage error.
        if not self._running and not self._corr.closed:
            raise RuntimeError("JSONRPCDispatcher.send_raw_request called before run()")
        plan = _plan_outbound(_related_request_id, opts)
        return await self._corr.call(
            method,
            params,
            opts,
            write_request=partial(self._write, metadata=plan.metadata),
            send_cancel=partial(self._cancel_outbound, related_request_id=_related_request_id),
            cancel_on_abandon=plan.cancel_on_abandon,
        )

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
        if self._corr.closed:
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
        on_notify_intercept: OnNotifyIntercept | None = None,
        *,
        task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        """Drive the receive loop until the read stream closes.

        `task_status.started()` fires once `send_raw_request` is usable.
        Single-shot: once the loop ends the dispatcher stays closed and cannot be restarted.
        """
        self._on_notify_intercept = on_notify_intercept
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
                        self._corr.close()
                    finally:
                        # Cancel in-flight handlers; otherwise the task-group join
                        # waits on handlers whose callers are already gone.
                        tg.cancel_scope.cancel()
        finally:
            # Covers cancel/crash paths that skip the inline close; idempotent.
            self._running = False
            self._tg = None
            self._corr.close()
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
        progress_token = progress_token_from_params(req.params)
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
        self._corr.enter_inbound(req.id, scope, dctx)
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
        here (they correlate against the correlator's in-flight/pending
        tables) and still teed to `on_notify` afterwards. The caller's
        `on_notify_intercept` then runs in receive order; only unconsumed
        notifications reach the spawned `on_notify`.
        """
        if msg.method == "notifications/cancelled":
            self._corr.peer_cancel(
                cancelled_request_id_from_params(msg.params),
                interrupt=self._peer_cancel_mode == "interrupt",
            )
        elif msg.method == "notifications/progress":
            delivery = self._corr.progress_callback(msg.params)
            if delivery is not None:
                fn, progress, total, message = delivery
                self._spawn(fn, progress, total, message, sender_ctx=sender_ctx)
        if run_notify_intercept(self._on_notify_intercept, msg.method, msg.params):
            return
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

    def _resolve_pending(self, request_id: RequestId | None, outcome: Outcome) -> None:
        self._corr.resolve(request_id, outcome)

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
        """Wake every pending `send_raw_request` waiter with `CONNECTION_CLOSED`. Idempotent."""
        self._corr.fan_out_closed()

    async def _handle_request(
        self,
        req: JSONRPCRequest,
        dctx: _JSONRPCDispatchContext[TransportT],
        scope: anyio.CancelScope,
        on_request: OnRequest,
    ) -> None:
        """Run `on_request` for one inbound request and write its response.

        The exception-to-wire policy lives in `RequestCorrelator.serve_inbound`;
        this only binds the wire writes for a stream-pair transport.
        """
        await self._corr.serve_inbound(
            req.id,
            dctx,
            scope,
            partial(on_request, dctx, req.method, req.params),
            write_result=partial(self._write_result, req.id),
            write_error=partial(self._write_error, req.id),
            raise_handler_exceptions=self._raise_handler_exceptions,
        )

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

    async def _cancel_outbound(self, request_id: RequestId, reason: str, related_request_id: RequestId | None) -> None:
        # Thread `related_request_id` so streamable HTTP routes the cancel onto
        # the request's own SSE stream instead of a possibly-absent GET stream.
        # `notify` swallows connection-state errors itself, so no guard here.
        await self.notify(
            "notifications/cancelled",
            {"requestId": request_id, "reason": reason},
            _related_request_id=related_request_id,
        )
