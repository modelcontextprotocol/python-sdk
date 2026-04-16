"""In-memory `Dispatcher` that wires two peers together with no transport.

`DirectDispatcher` is the simplest possible `Dispatcher` implementation: a call
on one side directly invokes the other side's `on_call`. There is no
serialization, no JSON-RPC framing, and no streams. It exists to:

* prove the `Dispatcher` Protocol is implementable without JSON-RPC
* provide a fast substrate for testing the layers above the dispatcher
  (`ServerRunner`, `Context`, `Connection`) without wire-level moving parts
* embed a server in-process when the JSON-RPC overhead is unnecessary

Unlike `JSONRPCDispatcher`, exceptions raised in a handler propagate directly
to the caller — there is no exception-to-`ErrorData` boundary here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import anyio

from mcp.shared.dispatcher import CallOptions, OnCall, OnNotify, ProgressFnT
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.shared.transport_context import TransportContext
from mcp.types import INTERNAL_ERROR, REQUEST_TIMEOUT

__all__ = ["DirectDispatcher", "create_direct_dispatcher_pair"]

DIRECT_TRANSPORT_KIND = "direct"


_Call = Callable[[str, Mapping[str, Any] | None, CallOptions | None], Awaitable[dict[str, Any]]]
_Notify = Callable[[str, Mapping[str, Any] | None], Awaitable[None]]


@dataclass
class _DirectDispatchContext:
    """`DispatchContext` for an inbound call on a `DirectDispatcher`.

    The back-channel callables target the *originating* side, so a handler's
    `send_request` reaches the peer that made the inbound call.
    """

    transport: TransportContext
    _back_call: _Call
    _back_notify: _Notify
    _on_progress: ProgressFnT | None = None
    cancel_requested: anyio.Event = field(default_factory=anyio.Event)

    async def notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        await self._back_notify(method, params)

    async def send_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        if not self.transport.can_send_request:
            raise NoBackChannelError(method)
        return await self._back_call(method, params, opts)

    async def progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        if self._on_progress is not None:
            await self._on_progress(progress, total, message)


class DirectDispatcher:
    """A `Dispatcher` that calls a peer's handlers directly, in-process.

    Two instances are wired together with `create_direct_dispatcher_pair`; each
    holds a reference to the other. `call` on one awaits the peer's `on_call`.
    `run` parks until `close` is called.
    """

    def __init__(self, transport_ctx: TransportContext):
        self._transport_ctx = transport_ctx
        self._peer: DirectDispatcher | None = None
        self._on_call: OnCall | None = None
        self._on_notify: OnNotify | None = None
        self._ready = anyio.Event()
        self._closed = anyio.Event()

    def connect_to(self, peer: DirectDispatcher) -> None:
        self._peer = peer

    async def call(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        if self._peer is None:
            raise RuntimeError("DirectDispatcher has no peer; use create_direct_dispatcher_pair()")
        return await self._peer._dispatch_call(method, params, opts)

    async def notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        if self._peer is None:
            raise RuntimeError("DirectDispatcher has no peer; use create_direct_dispatcher_pair()")
        await self._peer._dispatch_notify(method, params)

    async def run(self, on_call: OnCall, on_notify: OnNotify) -> None:
        self._on_call = on_call
        self._on_notify = on_notify
        self._ready.set()
        await self._closed.wait()

    def close(self) -> None:
        self._closed.set()

    def _make_context(self, on_progress: ProgressFnT | None = None) -> _DirectDispatchContext:
        assert self._peer is not None
        peer = self._peer
        return _DirectDispatchContext(
            transport=self._transport_ctx,
            _back_call=lambda m, p, o: peer._dispatch_call(m, p, o),
            _back_notify=lambda m, p: peer._dispatch_notify(m, p),
            _on_progress=on_progress,
        )

    async def _dispatch_call(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None,
    ) -> dict[str, Any]:
        await self._ready.wait()
        assert self._on_call is not None
        opts = opts or {}
        dctx = self._make_context(on_progress=opts.get("on_progress"))
        try:
            with anyio.fail_after(opts.get("timeout")):
                try:
                    return await self._on_call(dctx, method, params)
                except MCPError:
                    raise
                except Exception as e:
                    raise MCPError(code=INTERNAL_ERROR, message=str(e)) from e
        except TimeoutError:
            raise MCPError(
                code=REQUEST_TIMEOUT,
                message=f"Timed out after {opts.get('timeout')}s waiting for {method!r}",
            ) from None

    async def _dispatch_notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        await self._ready.wait()
        assert self._on_notify is not None
        dctx = self._make_context()
        await self._on_notify(dctx, method, params)


def create_direct_dispatcher_pair(
    *,
    can_send_request: bool = True,
) -> tuple[DirectDispatcher, DirectDispatcher]:
    """Create two `DirectDispatcher` instances wired to each other.

    Args:
        can_send_request: Sets `TransportContext.can_send_request` on both
            sides. Pass ``False`` to simulate a transport with no back-channel.

    Returns:
        A ``(left, right)`` pair. Conventionally ``left`` is the client side
        and ``right`` is the server side, but the wiring is symmetric.
    """
    ctx = TransportContext(kind=DIRECT_TRANSPORT_KIND, can_send_request=can_send_request)
    left = DirectDispatcher(ctx)
    right = DirectDispatcher(ctx)
    left.connect_to(right)
    right.connect_to(left)
    return left, right
