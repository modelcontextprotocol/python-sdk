"""JSON-RPC `Dispatcher` implementation.

Consumes the existing `SessionMessage`-based stream contract that all current
transports (stdio, SSE, streamable HTTP) speak. Owns request-id correlation,
the receive loop, per-request task isolation, cancellation/progress wiring, and
the single exception-to-wire boundary.

The MCP type layer (`ServerRunner`, `Context`, `Client`) sits above this and
sees only `(ctx, method, params) -> dict`. Transports sit below and see only
`SessionMessage` reads/writes.

The dispatcher is *mostly* MCP-agnostic — methods/params are opaque strings and
dicts — but it intercepts ``notifications/cancelled`` and
``notifications/progress`` because request correlation, cancellation and
progress are exactly the wiring this layer exists to provide. Those few wire
shapes are extracted with structural ``match`` patterns (no casts, no
``mcp.types`` model coupling); a malformed payload simply fails to match and
the correlation is skipped.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar, cast, overload

import anyio
import anyio.abc
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import ValidationError

from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.dispatcher import CallOptions, Dispatcher, OnNotify, OnRequest, ProgressFnT
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.shared.message import (
    ClientMessageMetadata,
    MessageMetadata,
    ServerMessageMetadata,
    SessionMessage,
)
from mcp.shared.transport_context import TransportContext
from mcp.types import (
    CONNECTION_CLOSED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    REQUEST_CANCELLED,
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

__all__ = ["JSONRPCDispatcher"]

logger = logging.getLogger(__name__)

TransportT = TypeVar("TransportT", bound=TransportContext)

PeerCancelMode = Literal["interrupt", "signal"]
"""How inbound ``notifications/cancelled`` is applied to a running handler.

``"interrupt"`` (default) cancels the handler's scope. ``"signal"`` only sets
``ctx.cancel_requested`` and lets the handler observe it cooperatively.
"""

TransportBuilder = Callable[[RequestId | None, MessageMetadata], TransportContext]
"""Builds the per-message `TransportContext` from the inbound JSON-RPC id and
the `SessionMessage.metadata` the transport attached. Defaults to a plain
`TransportContext(kind="jsonrpc", can_send_request=True)` when not supplied."""


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
    cancelled_by_peer: bool = False


@dataclass
class _JSONRPCDispatchContext(Generic[TransportT]):
    """Concrete `DispatchContext` produced for each inbound JSON-RPC message."""

    transport: TransportT
    _dispatcher: JSONRPCDispatcher[TransportT]
    _request_id: RequestId | None
    _progress_token: ProgressToken | None = None
    _closed: bool = False
    cancel_requested: anyio.Event = field(default_factory=anyio.Event)

    @property
    def can_send_request(self) -> bool:
        return self.transport.can_send_request and not self._closed

    async def notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        await self._dispatcher.notify(method, params, _related_request_id=self._request_id)

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


def _default_transport_builder(_request_id: RequestId | None, _meta: MessageMetadata) -> TransportContext:
    return TransportContext(kind="jsonrpc", can_send_request=True)


def _outbound_metadata(related_request_id: RequestId | None, opts: CallOptions | None) -> MessageMetadata:
    """Choose the `SessionMessage.metadata` for an outgoing request/notification.

    `ServerMessageMetadata` tags a server-to-client message with the inbound
    request it belongs to (so streamable-HTTP can route it onto that request's
    SSE stream). `ClientMessageMetadata` carries resumption hints to the
    client transport. ``None`` is the common case.
    """
    if related_request_id is not None:
        return ServerMessageMetadata(related_request_id=related_request_id)
    if opts:
        token = opts.get("resumption_token")
        on_token = opts.get("on_resumption_token")
        if token is not None or on_token is not None:
            return ClientMessageMetadata(resumption_token=token, on_resumption_token_update=on_token)
    return None


class JSONRPCDispatcher(Dispatcher[TransportT]):
    """`Dispatcher` over the existing `SessionMessage` stream contract.

    Inherits the `Dispatcher` Protocol explicitly so pyright checks
    conformance at the class definition rather than at first use.
    """

    @overload
    def __init__(
        self: JSONRPCDispatcher[TransportContext],
        read_stream: ReadStream[SessionMessage | Exception],
        write_stream: WriteStream[SessionMessage],
    ) -> None: ...
    @overload
    def __init__(
        self,
        read_stream: ReadStream[SessionMessage | Exception],
        write_stream: WriteStream[SessionMessage],
        *,
        transport_builder: Callable[[RequestId | None, MessageMetadata], TransportT],
        peer_cancel_mode: PeerCancelMode = "interrupt",
        raise_handler_exceptions: bool = False,
    ) -> None: ...
    def __init__(
        self,
        read_stream: ReadStream[SessionMessage | Exception],
        write_stream: WriteStream[SessionMessage],
        *,
        transport_builder: Callable[[RequestId | None, MessageMetadata], TransportT] | None = None,
        peer_cancel_mode: PeerCancelMode = "interrupt",
        raise_handler_exceptions: bool = False,
    ) -> None:
        self._read_stream = read_stream
        self._write_stream = write_stream
        # The overloads guarantee that when `transport_builder` is omitted,
        # `TransportT` is `TransportContext`, so the default is type-correct;
        # pyright can't see across overloads, hence the cast.
        self._transport_builder = cast(
            "Callable[[RequestId | None, MessageMetadata], TransportT]",
            transport_builder or _default_transport_builder,
        )
        self._peer_cancel_mode: PeerCancelMode = peer_cancel_mode
        self._raise_handler_exceptions = raise_handler_exceptions

        self._next_id = 0
        self._pending: dict[RequestId, _Pending] = {}
        self._in_flight: dict[RequestId, _InFlight[TransportT]] = {}
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

        ``_related_request_id`` is set only by `_JSONRPCDispatchContext` when a
        handler makes a server-to-client request mid-flight; it routes the
        outgoing message onto the correct per-request SSE stream (SHTTP) via
        `ServerMessageMetadata`. Top-level callers leave it ``None``.

        Raises:
            MCPError: The peer responded with a JSON-RPC error; or
                ``REQUEST_TIMEOUT`` if ``opts["timeout"]`` elapsed; or
                ``CONNECTION_CLOSED`` if the dispatcher shut down while
                awaiting the response.
            RuntimeError: Called before ``run()`` has started or after it has
                finished.
        """
        if not self._running:
            raise RuntimeError("JSONRPCDispatcher.send_raw_request called before run() / after close")
        opts = opts or {}
        request_id = self._allocate_id()
        out_params = dict(params) if params is not None else None
        on_progress = opts.get("on_progress")
        if on_progress is not None:
            # The caller wants progress updates. The spec mechanism is: include
            # `_meta.progressToken` on the request; the peer echoes that token on
            # any `notifications/progress` it sends. We use the request id as the
            # token so the receive loop can find this `_Pending.on_progress` by
            # `_pending[token]` without a second lookup table.
            meta = dict((out_params or {}).get("_meta") or {})
            meta["progressToken"] = request_id
            out_params = {**(out_params or {}), "_meta": meta}

        # buffer=1: at most one outcome is ever delivered. A `WouldBlock` from
        # `_resolve_pending`/`_fan_out_closed` means the waiter already has an
        # outcome and dropping the late/redundant signal is correct. buffer=0
        # is unsafe — there's a window between registering `_pending[id]` and
        # parking in `receive()` where a close signal would be lost.
        send, receive = anyio.create_memory_object_stream[dict[str, Any] | ErrorData](1)
        pending = _Pending(send=send, receive=receive, on_progress=on_progress)
        self._pending[request_id] = pending

        metadata = _outbound_metadata(_related_request_id, opts)
        msg = JSONRPCRequest(jsonrpc="2.0", id=request_id, method=method, params=out_params)
        try:
            await self._write(msg, metadata)
            with anyio.fail_after(opts.get("timeout")):
                outcome = await receive.receive()
        except TimeoutError:
            # Spec-recommended courtesy: tell the peer we've given up so it can
            # stop work and free resources. v1's BaseSession.send_request does
            # NOT do this; it's new behaviour.
            await self._cancel_outbound(request_id, f"timed out after {opts.get('timeout')}s")
            raise MCPError(code=REQUEST_TIMEOUT, message=f"Request {method!r} timed out") from None
        except anyio.get_cancelled_exc_class():
            # Our caller's scope was cancelled. We're already inside a cancelled
            # scope, so any bare `await` here re-raises immediately — shield to
            # let the courtesy cancel notification go out before we propagate.
            with anyio.CancelScope(shield=True):
                await self._cancel_outbound(request_id, "caller cancelled")
            raise
        finally:
            # Always remove the waiter, even on cancel/timeout, so a late
            # response from the peer (race) hits a closed stream and is dropped
            # in `_dispatch` rather than leaking.
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
        *,
        _related_request_id: RequestId | None = None,
    ) -> None:
        msg = JSONRPCNotification(jsonrpc="2.0", method=method, params=dict(params) if params is not None else None)
        await self._write(msg, _outbound_metadata(_related_request_id, None))

    async def run(
        self,
        on_request: OnRequest,
        on_notify: OnNotify,
        *,
        task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        """Drive the receive loop until the read stream closes.

        Each inbound request is handled in its own task in an internal task
        group; ``task_status.started()`` fires once that group is open, so
        ``await tg.start(dispatcher.run, ...)`` resumes when ``send_raw_request``
        is usable.
        """
        try:
            async with anyio.create_task_group() as tg:
                self._tg = tg
                self._running = True
                task_status.started()
                async with self._read_stream:
                    async for item in self._read_stream:
                        # Duck-typed: `_context_streams.ContextReceiveStream`
                        # exposes `.last_context` (the sender's contextvars
                        # snapshot per message). Plain memory streams don't.
                        sender_ctx: contextvars.Context | None = getattr(self._read_stream, "last_context", None)
                        self._dispatch(item, on_request, on_notify, sender_ctx)
                # Read stream EOF: wake any blocked `send_raw_request` waiters now,
                # *before* the task group joins, so handlers parked in
                # `dctx.send_raw_request()` can unwind and the join doesn't deadlock.
                self._running = False
                self._fan_out_closed()
        finally:
            # Covers the cancel/crash paths where the inline fan-out above is
            # never reached. Idempotent.
            self._running = False
            self._tg = None
            self._fan_out_closed()

    def _dispatch(
        self,
        item: SessionMessage | Exception,
        on_request: OnRequest,
        on_notify: OnNotify,
        sender_ctx: contextvars.Context | None,
    ) -> None:
        """Route one inbound item. Synchronous: never awaits.

        Everything here is `send_nowait` or `_spawn`. An `await` would let one
        slow message head-of-line block the entire read loop.
        """
        if isinstance(item, Exception):
            logger.debug("transport yielded exception: %r", item)
            return
        metadata = item.metadata
        msg = item.message
        match msg:
            case JSONRPCRequest():
                self._dispatch_request(msg, metadata, on_request, sender_ctx)
            case JSONRPCNotification():
                self._dispatch_notification(msg, metadata, on_notify, sender_ctx)
            case JSONRPCResponse():
                self._resolve_pending(msg.id, msg.result)
            case JSONRPCError():  # pragma: no branch
                # `id` may be None per JSON-RPC (parse error before id known).
                # The match is exhaustive over JSONRPCMessage; the no-match arc
                # on this final case is unreachable.
                self._resolve_pending(msg.id, msg.error)

    def _dispatch_request(
        self,
        req: JSONRPCRequest,
        metadata: MessageMetadata,
        on_request: OnRequest,
        sender_ctx: contextvars.Context | None,
    ) -> None:
        progress_token: ProgressToken | None
        match req.params:
            case {"_meta": {"progressToken": str() | int() as progress_token}}:
                pass
            case _:
                progress_token = None
        transport_ctx = self._transport_builder(req.id, metadata)
        dctx = _JSONRPCDispatchContext(
            transport=transport_ctx,
            _dispatcher=self,
            _request_id=req.id,
            _progress_token=progress_token,
        )
        scope = anyio.CancelScope()
        self._in_flight[req.id] = _InFlight(scope=scope, dctx=dctx)
        self._spawn(self._handle_request, req, dctx, scope, on_request, sender_ctx=sender_ctx)

    def _dispatch_notification(
        self,
        msg: JSONRPCNotification,
        metadata: MessageMetadata,
        on_notify: OnNotify,
        sender_ctx: contextvars.Context | None,
    ) -> None:
        if msg.method == "notifications/cancelled":
            match msg.params:
                case {"requestId": str() | int() as rid} if (in_flight := self._in_flight.get(rid)) is not None:
                    in_flight.cancelled_by_peer = True
                    in_flight.dctx.cancel_requested.set()
                    if self._peer_cancel_mode == "interrupt":
                        in_flight.scope.cancel()
                case _:
                    pass
            return
        if msg.method == "notifications/progress":
            match msg.params:
                case {"progressToken": str() | int() as token, "progress": int() | float() as progress} if (
                    pending := self._pending.get(token)
                ) is not None and pending.on_progress is not None:
                    total = msg.params.get("total")
                    message = msg.params.get("message")
                    self._spawn(
                        pending.on_progress,
                        float(progress),
                        float(total) if isinstance(total, int | float) else None,
                        message if isinstance(message, str) else None,
                        sender_ctx=sender_ctx,
                    )
                case _:
                    pass
            # fall through: progress is also teed to on_notify
        transport_ctx = self._transport_builder(None, metadata)
        dctx = _JSONRPCDispatchContext(transport=transport_ctx, _dispatcher=self, _request_id=None)
        self._spawn(on_notify, dctx, msg.method, msg.params, sender_ctx=sender_ctx)

    def _resolve_pending(self, request_id: RequestId | None, outcome: dict[str, Any] | ErrorData) -> None:
        pending = self._pending.get(request_id) if request_id is not None else None
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
        """Schedule ``fn(*args)`` in the run() task group, propagating the sender's contextvars.

        ASGI middleware (auth, OTel) sets contextvars on the request task that
        wrote into the read stream. ``Context.run(tg.start_soon, ...)`` makes
        the spawned handler inherit *that* context instead of the receive
        loop's, so ``auth_context_var`` and OTel spans survive.
        """
        assert self._tg is not None
        if sender_ctx is not None:
            sender_ctx.run(self._tg.start_soon, fn, *args)
        else:
            self._tg.start_soon(fn, *args)

    def _fan_out_closed(self) -> None:
        """Wake every pending ``send_raw_request`` waiter with ``CONNECTION_CLOSED``.

        Synchronous (uses ``send_nowait``) because it's called from ``finally``
        which may be inside a cancelled scope. Idempotent.
        """
        closed = ErrorData(code=CONNECTION_CLOSED, message="connection closed")
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
        """Run ``on_request`` for one inbound request and write its response.

        This is the single exception-to-wire boundary: handler exceptions are
        caught here and serialized to ``JSONRPCError``. Nothing above this in
        the stack constructs wire errors.
        """
        try:
            with scope:
                try:
                    result = await on_request(dctx, req.method, req.params)
                finally:
                    # Close the back-channel the moment the handler exits
                    # (success or raise), before the response write — a handler
                    # spawning detached work that later calls
                    # `dctx.send_raw_request()` should see `NoBackChannelError`.
                    dctx.close()
                await self._write_result(req.id, result)
            # Peer-cancel: `_dispatch_notification` cancelled this scope. anyio
            # swallows a scope's *own* cancel at __exit__, so the result write
            # (or the handler) is interrupted and execution lands here without
            # reaching the `except cancelled` arm below. Spec SHOULD: send no
            # response — fall through to `finally`.
        except anyio.get_cancelled_exc_class():
            # Outer-cancel: run()'s task group is shutting down. Any bare
            # `await` here re-raises immediately, so shield the courtesy write.
            with anyio.CancelScope(shield=True):
                await self._write_error(req.id, ErrorData(code=REQUEST_CANCELLED, message="Request cancelled"))
            raise
        except MCPError as e:
            await self._write_error(req.id, e.error)
        except ValidationError as e:
            await self._write_error(req.id, ErrorData(code=INVALID_PARAMS, message=str(e)))
        except Exception as e:
            logger.exception("handler for %r raised", req.method)
            await self._write_error(req.id, ErrorData(code=INTERNAL_ERROR, message=str(e)))
            if self._raise_handler_exceptions:
                raise
        finally:
            self._in_flight.pop(req.id, None)

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

    async def _cancel_outbound(self, request_id: RequestId, reason: str) -> None:
        try:
            await self.notify("notifications/cancelled", {"requestId": request_id, "reason": reason})
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            pass
