"""Dispatcher Protocol — the call/return boundary between transports and handlers.

A Dispatcher turns a duplex message channel into two things:

* an outbound API: ``send_request(method, params)`` and ``notify(method, params)``
* an inbound pump: ``run(on_request, on_notify)`` that drives the receive loop
  and invokes the supplied handlers for each incoming request/notification

It is deliberately *not* MCP-aware. Method names are strings, params and
results are ``dict[str, Any]``. The MCP type layer (request/result models,
capability negotiation, ``Context``) sits above this; the wire encoding
(JSON-RPC, gRPC, in-process direct calls) sits below it.

See ``JSONRPCDispatcher`` for the production implementation and
``DirectDispatcher`` for an in-memory implementation used in tests and for
embedding a server in-process.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, TypedDict, TypeVar, runtime_checkable

import anyio

from mcp.shared.transport_context import TransportContext

__all__ = [
    "CallOptions",
    "DispatchContext",
    "DispatchMiddleware",
    "Dispatcher",
    "OnNotify",
    "OnRequest",
    "Outbound",
    "ProgressFnT",
]

TransportT_co = TypeVar("TransportT_co", bound=TransportContext, covariant=True)


class ProgressFnT(Protocol):
    """Callback invoked when a progress notification arrives for a pending request."""

    async def __call__(self, progress: float, total: float | None, message: str | None) -> None: ...


class CallOptions(TypedDict, total=False):
    """Per-call options for `Outbound.send_request`.

    All keys are optional. Dispatchers ignore keys they do not understand.
    """

    timeout: float
    """Seconds to wait for a result before raising and sending ``notifications/cancelled``."""

    on_progress: ProgressFnT
    """Receive ``notifications/progress`` updates for this request."""

    resumption_token: str
    """Opaque token to resume a previously interrupted request (transport-dependent)."""

    on_resumption_token: Callable[[str], Awaitable[None]]
    """Receive a resumption token when the transport issues one."""


@runtime_checkable
class Outbound(Protocol):
    """Anything that can send requests and notifications to the peer.

    Both `Dispatcher` (top-level outbound) and `DispatchContext` (back-channel
    during an inbound request) extend this. `PeerMixin` wraps an `Outbound` to
    provide typed MCP request/notification methods.
    """

    async def send_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        """Send a request and await its result.

        Raises:
            MCPError: If the peer responded with an error, or the handler
                raised. Implementations normalize all handler exceptions to
                `MCPError` so callers see a single exception type.
        """
        ...

    async def notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        """Send a fire-and-forget notification."""
        ...


class DispatchContext(Outbound, Protocol[TransportT_co]):
    """Per-request context handed to ``on_request`` / ``on_notify``.

    Carries the transport metadata for the inbound message and provides the
    back-channel for sending requests/notifications to the peer while handling
    it. `send_request` raises `NoBackChannelError` if
    ``transport.can_send_request`` is ``False``.
    """

    @property
    def transport(self) -> TransportT_co:
        """Transport-specific metadata for this inbound message."""
        ...

    @property
    def cancel_requested(self) -> anyio.Event:
        """Set when the peer sends ``notifications/cancelled`` for this request."""
        ...

    async def progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        """Report progress for the inbound request, if the peer supplied a progress token.

        A no-op when no token was supplied.
        """
        ...


OnRequest = Callable[[DispatchContext[TransportContext], str, Mapping[str, Any] | None], Awaitable[dict[str, Any]]]
"""Handler for inbound requests: ``(ctx, method, params) -> result``. Raise ``MCPError`` to send an error response."""

OnNotify = Callable[[DispatchContext[TransportContext], str, Mapping[str, Any] | None], Awaitable[None]]
"""Handler for inbound notifications: ``(ctx, method, params)``."""

DispatchMiddleware = Callable[[OnRequest], OnRequest]
"""Wraps an ``OnRequest`` to produce another ``OnRequest``. Applied outermost-first."""


class Dispatcher(Outbound, Protocol[TransportT_co]):
    """A duplex request/notification channel with call-return semantics.

    Implementations own correlation of outbound requests to inbound results, the
    receive loop, per-request concurrency, and cancellation/progress wiring.
    """

    async def run(self, on_request: OnRequest, on_notify: OnNotify) -> None:
        """Drive the receive loop until the underlying channel closes.

        Each inbound request is dispatched to ``on_request`` in its own task;
        the returned dict (or raised ``MCPError``) is sent back as the response.
        Inbound notifications go to ``on_notify``.
        """
        ...
