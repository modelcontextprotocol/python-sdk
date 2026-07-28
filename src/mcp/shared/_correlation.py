"""Request correlation kernel shared by every JSON-RPC-shaped peer.

`RequestCorrelator` owns the two tables a peer needs regardless of how
messages travel: outbound requests awaiting the peer's response
(`pending`), and inbound requests currently being handled (`in_flight`),
together with everything that hangs off them - request-id minting and the
collision domain, progress routing, peer cancellation, the courtesy-cancel
policy on abandon, the connection-closed fan-out, and the single
exception-to-wire boundary for inbound handlers.

It knows nothing about framing or streams. Callers supply the write side
as callables: `JSONRPCDispatcher` writes `SessionMessage`s onto its stream
pair; the streamable-HTTP transport writes onto a request's response
channel. That is the whole difference between those transports at this
layer, so the semantics live here exactly once.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, Generic, Protocol

import anyio
import anyio.lowlevel
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp_types import (
    CONNECTION_CLOSED,
    INVALID_PARAMS,
    REQUEST_TIMEOUT,
    ErrorData,
    JSONRPCRequest,
    RequestId,
)
from opentelemetry.trace import SpanKind
from pydantic import ValidationError
from typing_extensions import TypeVar

from mcp.shared._otel import inject_trace_context, otel_span
from mcp.shared.dispatcher import CallOptions, ProgressFnT, coerce_request_id
from mcp.shared.exceptions import MCPError

__all__ = [
    "InFlight",
    "Outcome",
    "Pending",
    "RequestCorrelator",
    "handler_exception_to_error_data",
]

logger = logging.getLogger(__name__)

_ABANDON_WRITE_TIMEOUT: float = 5
"""Bound for courtesy-cancel writes on the abandon paths; the caller-cancel
arm shields its write, so a wedged transport would otherwise hang it uncancellably."""

_SHUTDOWN_WRITE_TIMEOUT: float = 1
"""Tighter bound for the shutdown-arm error write so a wedged transport can't hold session close."""

Outcome = dict[str, Any] | ErrorData
"""A request's terminal outcome: the result dict, or the peer's error."""


def handler_exception_to_error_data(exc: BaseException) -> ErrorData | None:
    """Map a handler-raised exception to its wire `ErrorData`.

    The two rungs every peer shares: an `MCPError` carries its own
    `ErrorData`; a pydantic `ValidationError` is the spec's INVALID_PARAMS
    with empty ``data`` (no pydantic text on the wire). Returns ``None`` for
    any other exception so each caller applies its own catch-all -
    `serve_inbound` currently pins ``code=0`` for v1 compat,
    the modern HTTP entry uses `INTERNAL_ERROR`.
    """
    if isinstance(exc, MCPError):
        return exc.error
    if isinstance(exc, ValidationError):
        return ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")
    return None


class _CancelObserver(Protocol):
    """The slice of a `DispatchContext` the in-flight table drives on peer cancel."""

    cancel_requested: anyio.Event

    def close(self) -> None: ...


DctxT = TypeVar("DctxT", bound=_CancelObserver, default=_CancelObserver)


@dataclass(slots=True)
class Pending:
    """An outbound request awaiting its response."""

    send: MemoryObjectSendStream[Outcome]
    receive: MemoryObjectReceiveStream[Outcome]
    on_progress: ProgressFnT | None = None


@dataclass(slots=True)
class InFlight(Generic[DctxT]):
    """An inbound request currently being handled."""

    scope: anyio.CancelScope
    dctx: DctxT


def _shielded_progress(fn: ProgressFnT) -> ProgressFnT:
    """Wrap a user progress callback so an exception can't cancel the caller's task group."""

    async def _wrapped(progress: float, total: float | None, message: str | None) -> None:
        try:
            await fn(progress, total, message)
        except Exception:
            logger.exception("progress callback raised")

    return _wrapped


async def final_write(
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


class RequestCorrelator(Generic[DctxT]):
    """Request-id correlation for one peer connection, in both directions.

    Outbound (`call`, `resolve`, `progress_callback`): requests this side
    sent that await the peer's response, keyed by the coerced request id
    (the collision domain `coerce_request_id` defines - `"7"` and `7` are
    one id even where the wire carries the value verbatim).

    Inbound (`enter_inbound`, `serve_inbound`, `peer_cancel`,
    `cancel_all_inbound`): requests the peer sent that this side is
    handling, so a `notifications/cancelled` from the peer (or a local
    shutdown) can interrupt exactly the right handler.

    `close()` is single-shot: once closed, `call` raises `MCPError`
    (`CONNECTION_CLOSED`) and every parked waiter is woken with the same.
    """

    def __init__(self) -> None:
        self.pending: dict[RequestId, Pending] = {}
        """Outbound requests awaiting a response, keyed by coerced request id."""
        self.in_flight: dict[RequestId, InFlight[DctxT]] = {}
        """Inbound requests being handled, keyed by coerced request id."""
        self._next_id = 0
        self._closed = False

    @property
    def closed(self) -> bool:
        """True once `close()` has run; `call` refuses and waiters were woken."""
        return self._closed

    def close(self) -> None:
        """Mark closed and wake every outbound waiter with `CONNECTION_CLOSED`. Idempotent, synchronous."""
        self._closed = True
        self.fan_out_closed()

    # ------------------------------------------------------------------
    # Outbound: requests this side sends and correlates against responses.
    # ------------------------------------------------------------------

    def allocate_id(self) -> int:
        """Mint the next dispatcher-owned request id (monotonic, starts at 1)."""
        self._next_id += 1
        return self._next_id

    def _reserve_id(self, supplied: RequestId | None) -> tuple[RequestId, RequestId]:
        """Pick the wire id and the pending-table key for one outbound request.

        A caller-supplied id is used verbatim on the wire and coerced for the
        key; a collision with an in-flight key raises `ValueError`. Otherwise
        a fresh id is minted past any key a supplied id occupies: the collision
        error is reserved for the caller who actually chose the id.
        """
        if supplied is not None:
            key = coerce_request_id(supplied)
            if key in self.pending:
                raise ValueError(f"request id {supplied!r} is already in flight")
            return supplied, key
        request_id = self.allocate_id()
        while request_id in self.pending:
            request_id = self.allocate_id()
        return request_id, request_id

    async def call(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None,
        *,
        write_request: Callable[[JSONRPCRequest], Awaitable[None]],
        send_cancel: Callable[[RequestId, str], Awaitable[None]],
        cancel_on_abandon: bool,
    ) -> dict[str, Any]:
        """Send one outbound request and await its correlated response.

        `write_request` puts the built `JSONRPCRequest` on the wire (raising
        `anyio.BrokenResourceError` / `ClosedResourceError` means the channel
        is gone). `send_cancel(request_id, reason)` emits the courtesy
        `notifications/cancelled` on the abandon paths when
        `cancel_on_abandon` is set; it must swallow its own write failures.

        Raises:
            MCPError: Peer error response; `REQUEST_TIMEOUT` if
                `opts["timeout"]` elapsed; `CONNECTION_CLOSED` if closed or
                the write channel was torn down.
            ValueError: `opts["request_id"]` collides with an in-flight id.
        """
        # Post-close sends get the same CONNECTION_CLOSED contract as in-flight waiters.
        if self._closed:
            raise MCPError(code=CONNECTION_CLOSED, message="Connection closed")
        opts = opts or {}
        request_id, pending_key = self._reserve_id(opts.get("request_id"))
        out_params = dict(params) if params is not None else {}
        out_meta = dict(out_params.get("_meta") or {})
        on_progress = opts.get("on_progress")
        if on_progress is not None:
            # The request id doubles as the progress token, so `pending[token]` finds `on_progress` directly.
            out_meta["progressToken"] = request_id
        out_params["_meta"] = out_meta

        # buffer=1: a close signal can arrive before the waiter parks in receive();
        # a WouldBlock later just means the waiter already has its one outcome.
        send, receive = anyio.create_memory_object_stream[Outcome](1)
        pending = Pending(send=send, receive=receive, on_progress=on_progress)
        self.pending[pending_key] = pending

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
        # middleware once that seam exists; the correlator should not own otel.
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
                    await write_request(msg)
                except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                    # Channel tore down before its owner noticed EOF; surface the documented contract.
                    raise MCPError(code=CONNECTION_CLOSED, message="Connection closed") from None
                with anyio.fail_after(opts.get("timeout")):
                    timeout_armed = True
                    outcome = await receive.receive()
        except TimeoutError:
            if not timeout_armed:
                # `fail_after` arms only after the write, so this TimeoutError is the
                # channel's own bounded send() failing - a transport error, not
                # `opts["timeout"]` elapsing. Propagate it raw (v1 kept the write
                # outside the timeout-catching try and did the same).
                raise
            # Courtesy cancel (spec-recommended) so the peer stops work;
            # unshielded so an outer caller cancellation can still interrupt the write.
            if cancel_on_abandon:
                await final_write(
                    partial(send_cancel, request_id, f"timed out after {opts.get('timeout')}s"),
                    shield=False,
                    timeout=_ABANDON_WRITE_TIMEOUT,
                    describe=f"courtesy cancel for timed-out request {request_id!r}",
                )
            raise MCPError(code=REQUEST_TIMEOUT, message=f"Request {method!r} timed out") from None
        except anyio.get_cancelled_exc_class():
            # Caller cancelled: bare awaits re-raise here, so the shielded helper
            # lets the courtesy cancel go out before we propagate.
            if cancel_on_abandon and request_write_started:
                await final_write(
                    partial(send_cancel, request_id, "caller cancelled"),
                    shield=True,
                    timeout=_ABANDON_WRITE_TIMEOUT,
                    describe=f"courtesy cancel for caller-cancelled request {request_id!r}",
                )
            raise
        finally:
            # Remove the waiter on every path so a late response is dropped, not leaked.
            self.pending.pop(pending_key, None)
            send.close()
            receive.close()

        if isinstance(outcome, ErrorData):
            raise MCPError(code=outcome.code, message=outcome.message, data=outcome.data)
        return outcome

    def resolve(self, request_id: RequestId | None, outcome: Outcome) -> None:
        """Deliver `outcome` to the waiter for `request_id`; unknown/late ids are dropped."""
        pending = self.pending.get(coerce_request_id(request_id)) if request_id is not None else None
        if pending is None:
            logger.debug("dropping response for unknown/late request id %r", request_id)
            return
        try:
            pending.send.send_nowait(outcome)
        except (anyio.WouldBlock, anyio.BrokenResourceError, anyio.ClosedResourceError):
            logger.debug("waiter for request id %r already gone", request_id)

    def progress_callback(
        self, params: Mapping[str, Any] | None
    ) -> tuple[ProgressFnT, float, float | None, str | None] | None:
        """Match a `notifications/progress` body against the pending outbound requests.

        Returns the shielded callback and its coerced arguments when the
        token names one of our requests that asked for progress, else `None`.
        `bool` is rejected everywhere it would alias an int/float.
        """
        match params:
            case {"progressToken": str() | int() as token, "progress": int() | float() as progress} if (
                not isinstance(token, bool)
                and not isinstance(progress, bool)
                and (pending := self.pending.get(coerce_request_id(token))) is not None
                and pending.on_progress is not None
            ):
                total = params.get("total")
                message = params.get("message")
                return (
                    _shielded_progress(pending.on_progress),
                    float(progress),
                    float(total) if isinstance(total, int | float) else None,
                    message if isinstance(message, str) else None,
                )
            case _:
                return None

    def fan_out_closed(self) -> None:
        """Wake every pending outbound waiter with `CONNECTION_CLOSED`.

        Synchronous: callers may be inside a cancelled scope. Idempotent.
        """
        closed = ErrorData(code=CONNECTION_CLOSED, message="Connection closed")
        for pending in self.pending.values():
            try:
                pending.send.send_nowait(closed)
            except (anyio.WouldBlock, anyio.BrokenResourceError, anyio.ClosedResourceError):
                pass
        self.pending.clear()

    # ------------------------------------------------------------------
    # Inbound: requests the peer sends and this side handles.
    # ------------------------------------------------------------------

    def enter_inbound(self, request_id: RequestId, scope: anyio.CancelScope, dctx: DctxT) -> None:
        """Register an inbound request before its handler runs, so peer cancels can find it.

        Duplicate ids blind-overwrite (v1/TS parity); the identity guard in
        `serve_inbound` keeps a superseded entry from evicting its successor.
        """
        # TODO(maxisbey): duplicate ids blind-overwrite (v1/TS parity); revisit
        # rejecting with INVALID_REQUEST. Key coerced so a stringified
        # `notifications/cancelled` id still correlates.
        self.in_flight[coerce_request_id(request_id)] = InFlight(scope=scope, dctx=dctx)

    def peer_cancel(self, request_id: RequestId | None, *, interrupt: bool) -> bool:
        """Apply a peer's `notifications/cancelled` for `request_id`.

        Sets the handler's `cancel_requested` event and, when `interrupt`,
        cancels its scope. Returns whether a matching in-flight request was found.
        """
        if request_id is None:
            return False
        in_flight = self.in_flight.get(coerce_request_id(request_id))
        if in_flight is None:
            return False
        in_flight.dctx.cancel_requested.set()
        if interrupt:
            in_flight.scope.cancel()
        return True

    def cancel_all_inbound(self) -> None:
        """Cancel every in-flight handler's scope (shutdown/termination)."""
        for entry in list(self.in_flight.values()):
            entry.scope.cancel()

    async def serve_inbound(
        self,
        request_id: RequestId,
        dctx: DctxT,
        scope: anyio.CancelScope,
        run: Callable[[], Awaitable[dict[str, Any]]],
        *,
        write_result: Callable[[dict[str, Any]], Awaitable[None]],
        write_error: Callable[[ErrorData], Awaitable[None]],
        settle_unanswered: Callable[[], Awaitable[None]] | None = None,
        raise_handler_exceptions: bool = False,
    ) -> None:
        """Run one registered inbound request and write at most one terminal outcome.

        The single exception-to-wire boundary for inbound requests. `run` is
        the handler invocation; `write_result`/`write_error` put the terminal
        response on whatever channel the transport uses (they must not raise
        for a torn-down channel). A request the peer cancelled is never
        answered (spec: MUST NOT send further messages for it): its result or
        error is dropped and it settles through `settle_unanswered` - the
        transport's hook for a wire that must still end the request another
        way. The caller registers `(request_id, scope, dctx)` via
        `enter_inbound` *before* scheduling this, so a peer cancel that races
        the handler's start still lands.
        """
        answer_write_started = False
        handler_failure: BaseException | None = None  # re-raised once the request settles
        try:
            with scope:
                try:
                    result = await run()
                finally:
                    # Close the back-channel and drop from `in_flight`; no checkpoint
                    # since handler return, so a peer cancel can't interleave.
                    # Identity guard: don't evict a duplicate id's newer entry.
                    dctx.close()
                    key = coerce_request_id(request_id)
                    if (entry := self.in_flight.get(key)) is not None and entry.dctx is dctx:
                        del self.in_flight[key]
                if not dctx.cancel_requested.is_set():
                    # A write interrupted by cancellation may still have delivered
                    # (a memory-stream send can hand its item to the receiver and
                    # still raise), so a started answer write counts as sent below:
                    # peers drop late responses, while a second answer for one id
                    # would break JSON-RPC.
                    answer_write_started = True
                    await write_result(result)
        except anyio.get_cancelled_exc_class():
            # Shutdown: answer the request so the peer isn't left waiting - unless
            # an answer write already started (it may have reached the channel;
            # prefer possibly-zero answers over possibly-two), or the peer already
            # cancelled it and stopped waiting. The shielded helper is needed
            # because bare awaits re-raise here.
            if not answer_write_started and not dctx.cancel_requested.is_set():
                await final_write(
                    partial(write_error, ErrorData(code=CONNECTION_CLOSED, message="Connection closed")),
                    shield=True,
                    timeout=_SHUTDOWN_WRITE_TIMEOUT,
                    describe=f"shutdown error response for request {request_id!r}",
                )
            raise
        except Exception as e:
            error = handler_exception_to_error_data(e)
            if error is None:
                logger.exception("handler for request %r raised", request_id)
                # TODO(L58): code=0 pins existing-server compat; JSON-RPC says
                # INTERNAL_ERROR. Revisit per the suite's divergence entry.
                error = ErrorData(code=0, message=str(e))
                if raise_handler_exceptions:
                    handler_failure = e
            # A cancel silences only the wire; the failure stays as visible as before.
            if not dctx.cancel_requested.is_set():
                answer_write_started = True
                await write_error(error)
        # The one place a cancelled request settles: the handler is done (any
        # mode) with nothing written. A peer-interrupt cancel is absorbed at
        # scope __exit__ and lands here too.
        if not answer_write_started and settle_unanswered is not None:
            try:
                await settle_unanswered()
            except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                logger.debug("on_request_unanswered dropped: connection closing")
            except Exception:
                logger.exception("on_request_unanswered hook raised")
        if handler_failure is not None:
            raise handler_failure
        # No `in_flight` pop here: the inner finally covers every path, and a late pop could evict a reused id.
