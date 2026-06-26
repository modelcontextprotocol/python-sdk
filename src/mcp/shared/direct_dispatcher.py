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
from mcp_types import CONNECTION_CLOSED, INTERNAL_ERROR, REQUEST_TIMEOUT, RequestId

from mcp.shared._compat import resync_tracer
from mcp.shared.dispatcher import CallOptions, OnNotify, OnRequest, ProgressFnT
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.shared.jsonrpc_dispatcher import handler_exception_to_error_data
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
    """A dispatcher-synthesized id for requests; `None` for notifications."""
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
        self._next_id = 0
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
                # Synthesize an id: the DispatchContext contract reserves None for notifications.
                self._next_id += 1
                dctx = self._make_context(on_progress=opts.get("on_progress"), request_id=self._next_id)
                try:
                    return await self._on_request(dctx, method, params)
                except Exception as e:
                    error, unexpected = handler_exception_to_error_data(e)
                    if unexpected and self._raise_handler_exceptions:
                        # In-process debugging: chain the real exception so the
                        # traceback survives. Never reaches the wire.
                        raise MCPError(code=INTERNAL_ERROR, message=str(e)) from e
                    if unexpected:
                        logger.exception("request handler raised")
                    raise MCPError(code=error.code, message=error.message, data=error.data) from None
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
