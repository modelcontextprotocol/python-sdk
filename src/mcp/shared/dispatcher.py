"""Dispatcher Protocol - the call/return boundary between transports and handlers.

A Dispatcher turns a duplex message channel into two things:

* an outbound API: `send_raw_request(method, params)` and `notify(method, params)`
* an inbound pump: `run(on_request, on_notify)` that drives the receive loop
  and invokes the supplied handlers for each incoming request/notification

It is deliberately *not* MCP-aware. Method names are strings, params and
results are `dict[str, Any]`. The MCP type layer (request/result models,
capability negotiation, `Context`) sits above this; the wire encoding
(JSON-RPC, gRPC, in-process direct calls) sits below it.

See `JSONRPCDispatcher` for the production implementation and
`DirectDispatcher` for an in-memory implementation used in tests and for
embedding a server in-process.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, TypedDict, TypeVar, runtime_checkable

import anyio
import anyio.abc

from mcp.shared.message import MessageMetadata
from mcp.shared.transport_context import TransportContext
from mcp.types import RequestId

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
    """Per-call options for `Outbound.send_raw_request`.

    All keys are optional. Dispatchers ignore keys they do not understand.
    """

    timeout: float
    """Seconds to wait for a result before raising and sending `notifications/cancelled`."""

    cancel_on_abandon: bool
    """Whether abandoning this request (timeout or caller cancellation) sends `notifications/cancelled`.

    Defaults to `True`. Set `False` for requests the protocol forbids cancelling, such as `initialize`.
    Also suppressed when resumption hints reach the transport, or when the request was never written.
    """

    on_progress: ProgressFnT
    """Receive `notifications/progress` updates for this request."""

    resumption_token: str
    """Opaque token to resume a previously interrupted request.

    Client-side, streamable-HTTP only. Ignored by server dispatchers and other
    transports, and also ignored (with a debug log) for requests sent from a
    `DispatchContext`, where routing onto the inbound request's stream takes
    precedence. Supports protocol version 2025-11-25 and earlier; SSE-stream
    resumption is removed in the next protocol revision.
    """

    on_resumption_token: Callable[[str], Awaitable[None]]
    """Receive a resumption token when the transport issues one for this request.

    Client-side, streamable-HTTP only. Ignored by server dispatchers and other
    transports, and also ignored (with a debug log) for requests sent from a
    `DispatchContext`, where routing onto the inbound request's stream takes
    precedence. Supports protocol version 2025-11-25 and earlier; SSE-stream
    resumption is removed in the next protocol revision.
    """


@runtime_checkable
class Outbound(Protocol):
    """Anything that can send requests and notifications to the peer.

    Both `Dispatcher` (top-level outbound) and `DispatchContext` (back-channel
    during an inbound request) extend this. The MCP type layer (`ClientPeer`,
    `Connection`) builds typed `send_request` / convenience methods on top of
    this raw channel.
    """

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        """Send a request and await its raw result dict.

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
    """Per-request context handed to `on_request` / `on_notify`.

    Carries the transport metadata for the inbound message and provides the
    back-channel for sending requests/notifications to the peer while handling
    it. `send_raw_request` raises `NoBackChannelError` if `can_send_request`
    is `False`.
    """

    @property
    def transport(self) -> TransportT_co:
        """Transport-specific metadata for this inbound message."""
        ...

    @property
    def can_send_request(self) -> bool:
        """Whether the back-channel can currently deliver server-initiated requests.

        `False` when the transport has no back-channel, or when this context has
        been closed (the inbound request finished). `send_raw_request` raises
        `NoBackChannelError` exactly when this is `False`.
        """
        ...

    @property
    def request_id(self) -> RequestId | None:
        """The id of the inbound request, or `None` for a notification.

        For JSON-RPC this is the wire `id` field. Handlers thread it through
        as `related_request_id` on outbound notifications so HTTP transports
        can route them onto the originating request's response stream.
        """
        ...

    @property
    def message_metadata(self) -> MessageMetadata:
        """The metadata the transport attached to this inbound message, if any.

        This is `SessionMessage.metadata` passed through verbatim: HTTP
        transports attach `ServerMessageMetadata` (the HTTP request, SSE
        stream-close callbacks); stdio and in-memory dispatch attach nothing.
        Tied to the `SessionMessage` wire format - goes away when transports
        stop delivering messages that way.
        """
        # TODO(maxisbey): remove for context rework
        ...

    @property
    def cancel_requested(self) -> anyio.Event:
        """Set when the peer sends `notifications/cancelled` for this request."""
        ...

    async def progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        """Report progress for the inbound request, if the peer supplied a progress token.

        A no-op when no token was supplied.
        """
        ...


OnRequest = Callable[[DispatchContext[TransportContext], str, Mapping[str, Any] | None], Awaitable[dict[str, Any]]]
"""Handler for inbound requests: `(ctx, method, params) -> result`. Raise `MCPError` to send an error response."""

OnNotify = Callable[[DispatchContext[TransportContext], str, Mapping[str, Any] | None], Awaitable[None]]
"""Handler for inbound notifications: `(ctx, method, params)`."""

DispatchMiddleware = Callable[[OnRequest], OnRequest]
"""Wraps an `OnRequest` to produce another `OnRequest`. Applied outermost-first."""


class Dispatcher(Outbound, Protocol[TransportT_co]):
    """A duplex request/notification channel with call-return semantics.

    Implementations own correlation of outbound requests to inbound results, the
    receive loop, per-request concurrency, and cancellation/progress wiring.

    The lifecycle surface is provisional; `run()` may change before v2 stable.
    """

    async def run(
        self,
        on_request: OnRequest,
        on_notify: OnNotify,
        *,
        task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        """Drive the receive loop until the underlying channel closes.

        Each inbound request is dispatched to `on_request` in its own task;
        the returned dict (or raised `MCPError`) is sent back as the response.
        Inbound notifications go to `on_notify`.

        `task_status.started()` is called once the dispatcher is ready to
        accept `send_request`/`notify` calls, so callers can use
        `await tg.start(dispatcher.run, on_request, on_notify)`.
        """
        ...
