"""In-memory `Dispatcher` that wires two peers together with no transport.

`DirectDispatcher` is the simplest possible `Dispatcher` implementation: a
request on one side directly invokes the other side's `on_request`. There is no
serialization, no JSON-RPC framing, and no streams. It exists to:

* prove the `Dispatcher` Protocol is implementable without JSON-RPC
* provide a fast substrate for testing the layers above the dispatcher
  (`ServerRunner`, `Context`, `Connection`) without wire-level moving parts
* embed a server in-process when the JSON-RPC overhead is unnecessary

Like `JSONRPCDispatcher`, this is an exception-to-error boundary: a handler
exception surfaces to the caller as `MCPError`. The `raise_handler_exceptions`
knob controls whether unmapped exceptions are sanitized (matching the wire
path) or chained as ``__cause__`` for in-process debugging.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import anyio
import anyio.abc
from mcp_types import CONNECTION_CLOSED, INTERNAL_ERROR, INVALID_PARAMS, REQUEST_TIMEOUT, RequestId
from pydantic import ValidationError

from mcp.shared._compat import resync_tracer
from mcp.shared.dispatcher import (
    CallOptions,
    OnNotify,
    OnNotifyIntercept,
    OnRequest,
    ProgressFnT,
    coerce_request_id,
    run_notify_intercept,
)
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.shared.message import MessageMetadata
from mcp.shared.transport_context import TransportContext

logger = logging.getLogger(__name__)

__all__ = ["DirectDispatcher", "create_direct_dispatcher_pair"]

DIRECT_TRANSPORT_KIND = "direct"


_Request = Callable[[str, Mapping[str, Any] | None, CallOptions | None], Awaitable[dict[str, Any]]]
_Notify = Callable[[str, Mapping[str, Any] | None], Awaitable[None]]


@dataclass
class _DirectDispatchContext:
    """`DispatchContext` for an inbound request on a `DirectDispatcher`.

    The back-channel callables target the *originating* side, so a handler's
    `send_raw_request` reaches the peer that made the inbound request.
    """

    transport: TransportContext
    _back_request: _Request
    _back_notify: _Notify
    request_id: RequestId | None = None
    """The caller-supplied `CallOptions["request_id"]`, else a dispatcher-synthesized
    id for requests; `None` for notifications."""
    message_metadata: MessageMetadata = None  # TODO(maxisbey): remove for Context rework
    """Always `None`: in-memory dispatch attaches no transport metadata."""
    _on_progress: ProgressFnT | None = None
    cancel_requested: anyio.Event = field(default_factory=anyio.Event)

    @property
    def can_send_request(self) -> bool:
        return self.transport.can_send_request

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        await self._back_notify(method, params)

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        if not self.can_send_request:
            raise NoBackChannelError(method)
        return await self._back_request(method, params, opts)

    async def progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        if self._on_progress is not None:
            await self._on_progress(progress, total, message)


class DirectDispatcher:
    """A `Dispatcher` that calls a peer's handlers directly, in-process.

    Two instances are wired together with `create_direct_dispatcher_pair`; each
    holds a reference to the other. `send_raw_request` on one awaits the peer's
    `on_request`. `run` parks until `close` is called.

    Lifecycle mirrors `JSONRPCDispatcher`: `send_raw_request` requires `run()`
    to have started, and once a side has closed - via `close()` or `run()`
    ending - `send_raw_request` raises `MCPError` (`CONNECTION_CLOSED`) and
    inbound requests fail the peer's call the same way instead of invoking the
    handler. Notifications are fire-and-forget in both directions: after close
    they are silently dropped.
    """

    def __init__(self, transport_ctx: TransportContext, *, raise_handler_exceptions: bool = True):
        self._transport_ctx = transport_ctx
        self._raise_handler_exceptions = raise_handler_exceptions
        self._peer: DirectDispatcher | None = None
        self._on_request: OnRequest | None = None
        self._on_notify: OnNotify | None = None
        self._on_notify_intercept: OnNotifyIntercept | None = None
        self._next_id = 0
        self._in_flight_ids: set[RequestId] = set()
        self._ready = anyio.Event()
        self._close_event = anyio.Event()
        self._running = False
        self._closed = False

    def connect_to(self, peer: DirectDispatcher) -> None:
        self._peer = peer

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        """Send a request by invoking the peer's `on_request` directly.

        Raises:
            MCPError: The peer's handler raised; `REQUEST_TIMEOUT` if
                `opts["timeout"]` elapsed; `CONNECTION_CLOSED` if either
                side has closed.
            RuntimeError: Called before `run()`.
        """
        if self._peer is None:
            raise RuntimeError("DirectDispatcher has no peer; use create_direct_dispatcher_pair()")
        # Post-close sends get the same CONNECTION_CLOSED contract as JSONRPCDispatcher.
        if self._closed:
            raise MCPError(code=CONNECTION_CLOSED, message="Connection closed")
        if not self._running:
            raise RuntimeError("DirectDispatcher.send_raw_request called before run()")
        return await self._peer._dispatch_request(method, params, opts)

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        """Send a notification by invoking the peer's `on_notify` directly.

        Fire-and-forget: usable before `run()` (delivery waits for the peer to
        start), and after close it is silently dropped, matching
        `JSONRPCDispatcher.notify`. `opts` is accepted for `Dispatcher`
        conformance; there is no HTTP layer here so `headers` is ignored.
        """
        if self._peer is None:
            raise RuntimeError("DirectDispatcher has no peer; use create_direct_dispatcher_pair()")
        if self._closed:
            logger.debug("dropped notification %r on closed DirectDispatcher", method)
            return
        await self._peer._dispatch_notify(method, params)

    async def run(
        self,
        on_request: OnRequest,
        on_notify: OnNotify,
        on_notify_intercept: OnNotifyIntercept | None = None,
        *,
        task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        """Mark this side ready and park until `close()` is called.

        Single-shot, like `JSONRPCDispatcher.run`: once it returns the
        dispatcher stays closed and cannot be restarted.
        """
        try:
            self._on_request = on_request
            self._on_notify = on_notify
            self._on_notify_intercept = on_notify_intercept
            self._running = True
            self._ready.set()
            task_status.started()
            await self._close_event.wait()
        finally:
            self._running = False
            self._closed = True
            # run() may end via cancellation without close() ever being
            # called; setting the event wakes `_wait_ready` waiters so they
            # observe the closed state instead of parking forever.
            self._close_event.set()

    def close(self) -> None:
        self._closed = True
        self._close_event.set()

    def _make_context(
        self, on_progress: ProgressFnT | None = None, request_id: RequestId | None = None
    ) -> _DirectDispatchContext:
        assert self._peer is not None
        peer = self._peer
        return _DirectDispatchContext(
            transport=self._transport_ctx,
            _back_request=lambda m, p, o: peer._dispatch_request(m, p, o),
            _back_notify=lambda m, p: peer._dispatch_notify(m, p),
            request_id=request_id,
            _on_progress=on_progress,
        )

    async def _wait_ready(self) -> None:
        """Park until `run()` has started, waking early if this side closes.

        Raises:
            MCPError: `CONNECTION_CLOSED` if this side has closed.
        """
        if not self._ready.is_set() and not self._close_event.is_set():
            async with anyio.create_task_group() as tg:

                async def wake_on(event: anyio.Event) -> None:
                    await event.wait()
                    tg.cancel_scope.cancel()

                tg.start_soon(wake_on, self._ready)
                tg.start_soon(wake_on, self._close_event)
        if self._closed:
            raise MCPError(code=CONNECTION_CLOSED, message="Connection closed")

    async def _dispatch_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None,
    ) -> dict[str, Any]:
        opts = opts or {}
        try:
            with anyio.fail_after(opts.get("timeout")):
                # Inside the timeout scope, so a configured timeout also bounds
                # waiting on a peer whose run() has not started yet.
                await self._wait_ready()
                assert self._on_request is not None
                supplied_id = opts.get("request_id")
                if supplied_id is not None:
                    request_id: RequestId = supplied_id
                    # Collisions use the same coerced domain as JSONRPCDispatcher's
                    # pending keys, so this in-memory stand-in raises for exactly
                    # the ids the wire dispatcher would; the context still sees
                    # the verbatim value.
                    in_flight_key = coerce_request_id(request_id)
                    if in_flight_key in self._in_flight_ids:
                        raise ValueError(f"request id {request_id!r} is already in flight")
                    # Advance the mint counter past the supplied key: ids are
                    # single-use within a session, so a minted id may not
                    # revisit this key even after the request completes.
                    if isinstance(in_flight_key, int):
                        self._next_id = max(self._next_id, in_flight_key)
                else:
                    # Synthesize an id (the DispatchContext contract reserves None
                    # for notifications). Cannot collide: the counter is past
                    # every supplied integer key (advanced above) and every
                    # previously minted id; the collision error is reserved for
                    # the caller who actually chose the id.
                    self._next_id += 1
                    request_id = self._next_id
                    in_flight_key = request_id
                self._in_flight_ids.add(in_flight_key)
                dctx = self._make_context(on_progress=opts.get("on_progress"), request_id=request_id)
                try:
                    return await self._on_request(dctx, method, params)
                except MCPError:
                    raise
                except ValidationError as e:
                    # Same shape JSONRPCDispatcher writes, so runner-over-direct
                    # tests see what runner-over-JSONRPC would.
                    raise MCPError(code=INVALID_PARAMS, message="Invalid request parameters", data="") from e
                except Exception as e:
                    # Single owner of the in-proc exception-to-error policy (mirrors
                    # JSONRPCDispatcher / `_streamable_http_modern._to_jsonrpc_response`
                    # for the wire paths). True chains the original for in-process
                    # debugging; False sanitizes to match the wire path's leak guard.
                    if self._raise_handler_exceptions:
                        raise MCPError(code=INTERNAL_ERROR, message=str(e)) from e
                    logger.exception("request handler raised")
                    raise MCPError(code=INTERNAL_ERROR, message="Internal server error") from None
                finally:
                    self._in_flight_ids.discard(in_flight_key)
        except TimeoutError:
            raise MCPError(
                code=REQUEST_TIMEOUT,
                message=f"Timed out after {opts.get('timeout')}s waiting for {method!r}",
            ) from None
        finally:
            await resync_tracer()

    async def _dispatch_notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        try:
            await self._wait_ready()
        except MCPError:
            # Notifications are fire-and-forget: a notify to a closed peer is
            # dropped, not raised back into the sender's call.
            logger.debug("dropped notification %r to closed DirectDispatcher", method)
            return
        if run_notify_intercept(self._on_notify_intercept, method, params):
            return
        assert self._on_notify is not None
        dctx = self._make_context()
        await self._on_notify(dctx, method, params)


def create_direct_dispatcher_pair(
    *,
    can_send_request: bool = True,
    headers: Mapping[str, str] | None = None,
    raise_handler_exceptions: bool = True,
) -> tuple[DirectDispatcher, DirectDispatcher]:
    """Create two `DirectDispatcher` instances wired to each other.

    Args:
        can_send_request: Sets `TransportContext.can_send_request` on both
            sides. Pass `False` to simulate a transport with no back-channel.
        headers: Sets `TransportContext.headers` on both sides.
        raise_handler_exceptions: When `True` (the default - this is an
            in-process debugging substrate), an unmapped handler exception
            reaches the caller as `MCPError` with the original chained as
            ``__cause__``. When `False` it is sanitized to an opaque
            `INTERNAL_ERROR` so the in-process path matches the wire.

    Returns:
        A `(client, server)` pair. The wiring is symmetric, so the roles
        are conventional only.
    """
    ctx = TransportContext(kind=DIRECT_TRANSPORT_KIND, can_send_request=can_send_request, headers=headers)
    client = DirectDispatcher(ctx, raise_handler_exceptions=raise_handler_exceptions)
    server = DirectDispatcher(ctx, raise_handler_exceptions=raise_handler_exceptions)
    client.connect_to(server)
    server.connect_to(client)
    return client, server
