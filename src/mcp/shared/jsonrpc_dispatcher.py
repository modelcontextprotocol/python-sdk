"""JSON-RPC `Dispatcher` implementation.

Consumes the existing `SessionMessage`-based stream contract that all current
transports (stdio, SSE, streamable HTTP) speak. Owns request-id correlation,
the receive loop, per-request task isolation, cancellation/progress wiring, and
the single exception-to-wire boundary.

The MCP type layer (`ServerRunner`, `Context`, `Client`) sits above this and
sees only `(ctx, method, params) -> dict`. Transports sit below and see only
`SessionMessage` reads/writes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar, overload

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.dispatcher import CallOptions, OnNotify, OnRequest, ProgressFnT
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.shared.message import (
    ClientMessageMetadata,
    MessageMetadata,
    ServerMessageMetadata,
    SessionMessage,
)
from mcp.shared.transport_context import TransportContext
from mcp.types import (
    REQUEST_TIMEOUT,
    ErrorData,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
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

    async def send_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        if not self.can_send_request:
            raise NoBackChannelError(method)
        return await self._dispatcher.send_request(method, params, opts, _related_request_id=self._request_id)

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


class JSONRPCDispatcher(Generic[TransportT]):
    """`Dispatcher` over the existing `SessionMessage` stream contract."""

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
        self._transport_builder = transport_builder or _default_transport_builder
        self._peer_cancel_mode: PeerCancelMode = peer_cancel_mode
        self._raise_handler_exceptions = raise_handler_exceptions

        self._next_id = 0
        self._pending: dict[RequestId, _Pending] = {}
        self._in_flight: dict[RequestId, _InFlight[TransportT]] = {}
        self._running = False

    async def send_request(
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
            raise RuntimeError("JSONRPCDispatcher.send_request called before run() / after close")
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

    async def run(self, on_request: OnRequest, on_notify: OnNotify) -> None:
        raise NotImplementedError  # chunk (b)

    def _allocate_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def _write(self, message: JSONRPCMessage, metadata: MessageMetadata = None) -> None:
        await self._write_stream.send(SessionMessage(message=message, metadata=metadata))

    async def _cancel_outbound(self, request_id: RequestId, reason: str) -> None:
        try:
            await self.notify("notifications/cancelled", {"requestId": request_id, "reason": reason})
        except anyio.BrokenResourceError:
            pass
        except anyio.ClosedResourceError:
            pass
