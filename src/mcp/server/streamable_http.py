"""StreamableHTTP Server Transport Module

This module implements the (2025-era, sessionful) Streamable HTTP transport.

Each HTTP request is served directly: a POSTed JSON-RPC request is
dispatched to the server's handler kernel and its outbound messages flow into
a per-request `_MessageChannel` - the response's own SSE stream, backed by
the optional `EventStore` for resumability - rather than through a shared
message pipe. A POSTed JSON-RPC response resolves the server-to-client request
awaiting it; a POSTed notification is handled after the `202`. The standalone
GET stream is one more channel, connection-scoped, for messages related to
no request.

`StreamableHTTPServerTransport` is therefore the per-session core (session
id, connection state, correlation of server-to-client requests, the open
channels); `StreamableHTTPSessionManager` creates one per `Mcp-Session-Id`
(or a fresh one per request in stateless mode) and routes ASGI requests to it.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

import anyio
import anyio.abc
import pydantic_core
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp_types import (
    DEFAULT_NEGOTIATED_VERSION,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    PARSE_ERROR,
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    RequestId,
    jsonrpc_message_adapter,
)
from mcp_types.version import is_version_at_least
from pydantic import ValidationError
from sse_starlette import EventSourceResponse
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from mcp.server.connection import Connection
from mcp.server.runner import ServerRunner, aclose_shielded
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from mcp.shared._correlation import RequestCorrelator
from mcp.shared.dispatcher import CallOptions
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER
from mcp.shared.jsonrpc_dispatcher import cancelled_request_id_from_params, progress_token_from_params
from mcp.shared.message import ServerMessageMetadata
from mcp.shared.transport_context import TransportContext

if TYPE_CHECKING:
    from mcp.server.lowlevel.server import Server

logger = logging.getLogger(__name__)


# Header names
MCP_SESSION_ID_HEADER = "mcp-session-id"
LAST_EVENT_ID_HEADER = "last-event-id"

# Content types
CONTENT_TYPE_JSON = "application/json"
CONTENT_TYPE_SSE = "text/event-stream"

# Special key for the standalone GET stream
GET_STREAM_KEY = "_GET_stream"

# Buffer between a channel and the SSE response draining it, so a handler can
# run this far ahead of a slow client before its own writes apply backpressure.
REQUEST_STREAM_BUFFER_SIZE: Final = 16

# Error code answering a request that settled without a response (e.g. it was
# cancelled) on this 2025-era wire, which ends a request's stream only with a
# response. Mirrors LSP's RequestCancelled; not sent by the 2026 transports, where
# the spec forbids answering a cancelled request. See
# `StreamableHTTPServerTransport._settle_unanswered_request`.
REQUEST_CANCELLED: Final = -32800

# Session ID validation pattern (visible ASCII characters ranging from 0x21 to 0x7E)
# Pattern ensures entire string contains only valid characters by using ^ and $ anchors
SESSION_ID_PATTERN = re.compile(r"^[\x21-\x7E]+$")

# Type aliases
StreamId = str
EventId = str
# An SSE event-dict as accepted by sse-starlette (`event`, `data`, `id`, `retry`).
SSEEvent = dict[str, Any]


def check_accept_headers(request: Request) -> tuple[bool, bool]:
    """Return (has_json, has_sse) for the request's Accept header, with RFC 7231 wildcard handling.

    Supports wildcard media types per RFC 7231, section 5.3.2:
    - */* matches any media type
    - application/* matches any application/ subtype
    - text/* matches any text/ subtype
    """
    accept_header = request.headers.get("accept", "")
    accept_types = [media_type.strip().split(";")[0].strip().lower() for media_type in accept_header.split(",")]

    has_wildcard = "*/*" in accept_types
    has_json = has_wildcard or any(t in (CONTENT_TYPE_JSON, "application/*") for t in accept_types)
    has_sse = has_wildcard or any(t in (CONTENT_TYPE_SSE, "text/*") for t in accept_types)

    return has_json, has_sse


@dataclass
class EventMessage:
    """A JSONRPCMessage with an optional event ID for stream resumability."""

    message: JSONRPCMessage
    event_id: str | None = None


EventCallback = Callable[[EventMessage], Awaitable[None]]


class EventStore(ABC):
    """Interface for resumability support via event storage."""

    @abstractmethod
    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        """Stores an event for later retrieval.

        Args:
            stream_id: ID of the stream the event belongs to
            message: The JSON-RPC message to store, or None for priming events

        Returns:
            The generated event ID for the stored event.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        """Replays events that occurred after the specified event ID.

        Args:
            last_event_id: The ID of the last event the client received
            send_callback: A callback function to send events to the client

        Returns:
            The stream ID of the replayed events - the same id `store_event`
            received for them - or None if no events were found. The transport
            only releases a replay for a stream id it minted itself.
        """
        pass  # pragma: no cover


class _MessageChannel:
    """One SSE stream's outbound messages: a request's response stream, or the standalone GET stream.

    Every message is first offered to the `EventStore` (so a client that
    drops the connection can resume via `Last-Event-ID`), then forwarded to
    the SSE response currently attached to the channel, if any. A store that
    fails degrades resumability - the failure is logged and the message still
    goes out live - it never takes the stream down; `closed` means only that
    the stream's life is over (its request finished, or the session ended).
    """

    def __init__(self, stream_id: StreamId, event_store: EventStore | None) -> None:
        self.stream_id = stream_id
        self._event_store = event_store
        self._writer: MemoryObjectSendStream[EventMessage] | None = None
        self._reader: MemoryObjectReceiveStream[EventMessage] | None = None
        self._closed = False
        # Store-then-forward is one atomic step per channel, so the wire order
        # of concurrent writers always matches the order the event store saw
        # (what a `Last-Event-ID` resume replays from).
        self._write_lock = anyio.Lock()
        self.terminal: JSONRPCResponse | JSONRPCError | None = None
        """The terminal outcome once the request this channel serves has finished."""
        self.finished = anyio.Event()
        """Set once `terminal` is recorded, or the channel is finished/closed without one."""

    @property
    def attached(self) -> bool:
        """Whether an SSE response is currently draining this channel."""
        return self._writer is not None

    async def write(self, message: JSONRPCMessage) -> bool:
        """Store-then-forward one outbound message. Never raises.

        Returns whether the message reached somewhere the client can still get
        it - the event store, or the currently attached response. `False`
        means it was dropped: the stream is over, or nothing could hold it.
        """
        async with self._write_lock:
            if self._closed:
                logger.debug("dropped message on closed stream %s", self.stream_id)
                return False
            # Store the event if we have an event store,
            # regardless of whether a client is connected
            # messages will be replayed on the re-connect
            event_id: EventId | None = None
            if self._event_store is not None:
                try:
                    event_id = await self._event_store.store_event(self.stream_id, message)
                except Exception:
                    # A broken store costs resumability for this message, not the
                    # stream: log (its text never reaches the wire) and still
                    # deliver live below.
                    logger.exception("EventStore.store_event failed for stream %s", self.stream_id)
                else:
                    logger.debug(f"Stored {event_id} from {self.stream_id}")
            if isinstance(message, JSONRPCResponse | JSONRPCError):
                self.terminal = message
                self.finished.set()
            writer = self._writer
            if writer is None:
                logger.debug(
                    f"""Request stream {self.stream_id} is not connected
                    for message. Still processing message as the client
                    might reconnect and replay."""
                )
                # Retrievable later only if the store took it.
                return event_id is not None
            try:
                await writer.send(EventMessage(message, event_id))
            except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                # The response's reader closed under the send; the response's
                # own cleanup detaches this attachment.
                return event_id is not None
            return True

    def attach(self) -> MemoryObjectReceiveStream[EventMessage] | None:
        """Attach a fresh SSE response and return the reader it drains.

        Returns `None` when the stream's life is already over, so no response
        can attach to a dead channel. Callers check `attached` first where a
        second reader is an error (the standalone GET stream); re-attaching
        after a detach is how a `Last-Event-ID` reconnect resumes a live stream.
        """
        if self._closed:
            return None
        assert self._writer is None, "every attach site checks `attached` first"
        writer, reader = anyio.create_memory_object_stream[EventMessage](REQUEST_STREAM_BUFFER_SIZE)
        self._writer, self._reader = writer, reader
        return reader

    def detach(self, reader: MemoryObjectReceiveStream[EventMessage] | None = None) -> None:
        """Detach the current SSE response so the request can carry on without it.

        `reader` scopes the detach to the attachment that reader came from: a
        stale response ending must not knock a newer (resumed) attachment off
        the channel. With no `reader`, whatever is attached is detached.
        """
        if self._writer is None:
            return
        if reader is not None and reader is not self._reader:
            return
        self._writer.close()
        self._writer, self._reader = None, None

    def close(self) -> None:
        """The stream is over: detach any response and drop every further write.

        Serves both request completion (the terminal frame normally ended the
        response already; this covers one whose terminal write never landed, so
        the client sees the stream close rather than hang) and session
        termination. Frames already buffered still drain to their reader.
        """
        self._closed = True
        self.finished.set()
        self.detach()


@dataclass
class _HTTPRequestDispatchContext:
    """`DispatchContext` for one JSON-RPC message received over streamable HTTP.

    For a request POST, `channel` is that request's response stream: request
    scoped notifications, progress, and server-to-client requests all ride it.
    For a notification POST there is no request in flight, so the same
    operations ride the connection's standalone stream instead.
    """

    transport: TransportContext
    _corr: RequestCorrelator[_HTTPRequestDispatchContext]
    _channel: _MessageChannel
    _request_id: RequestId | None
    message_metadata: ServerMessageMetadata | None = None  # TODO(maxisbey): remove for Context rework
    """The per-request HTTP `Request` and SSE close callbacks the server lifts onto its request context."""
    _progress_token: RequestId | None = None
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
        await self._channel.write(_notification(method, params))

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        if not self.can_send_request:
            raise NoBackChannelError(method)
        return await _call_over_channel(self._corr, self._channel, method, params, opts)

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


class _StandaloneOutbound:
    """The connection's `Outbound`: server-initiated messages on the standalone GET stream."""

    def __init__(self, corr: RequestCorrelator[_HTTPRequestDispatchContext], channel: _MessageChannel) -> None:
        self._corr = corr
        self._channel = channel

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        return await _call_over_channel(self._corr, self._channel, method, params, opts)

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        await self._channel.write(_notification(method, params))


def _notification(method: str, params: Mapping[str, Any] | None) -> JSONRPCNotification:
    # Leave `params` unset when None: with `exclude_unset=True` an explicit
    # None would serialize as `"params": null`, which JSON-RPC 2.0 forbids.
    if params is not None:
        return JSONRPCNotification(jsonrpc="2.0", method=method, params=dict(params))
    return JSONRPCNotification(jsonrpc="2.0", method=method)


async def _call_over_channel(
    corr: RequestCorrelator[_HTTPRequestDispatchContext],
    channel: _MessageChannel,
    method: str,
    params: Mapping[str, Any] | None,
    opts: CallOptions | None,
) -> dict[str, Any]:
    """Send a server-to-client request on `channel` and await the client's POSTed response.

    The whole abandon policy (timeout, caller cancel, courtesy
    `notifications/cancelled` written to the same channel) is the shared
    `RequestCorrelator`'s; only the write side is HTTP-specific.
    """
    opts = opts or {}

    async def write_request(message: JSONRPCRequest) -> None:
        if not await channel.write(message):
            # Neither stored nor delivered live: the request can never reach
            # the client, so fail the caller (the correlator surfaces
            # CONNECTION_CLOSED) rather than await an answer that cannot come.
            raise anyio.ClosedResourceError

    async def send_cancel(request_id: RequestId, reason: str) -> None:
        await channel.write(_notification("notifications/cancelled", {"requestId": request_id, "reason": reason}))

    return await corr.call(
        method,
        params,
        opts,
        write_request=write_request,
        send_cancel=send_cancel,
        cancel_on_abandon=opts.get("cancel_on_abandon", True),
    )


class StreamableHTTPServerTransport:
    """HTTP server transport with event streaming support for MCP.

    Handles JSON-RPC messages in HTTP POST requests with SSE streaming.
    Supports optional JSON responses and session management. One instance
    serves one session (or, in stateless mode, one request); the
    `StreamableHTTPSessionManager` creates and routes to them.
    """

    _security: TransportSecurityMiddleware

    def __init__(
        self,
        mcp_session_id: str | None,
        is_json_response_enabled: bool = False,
        event_store: EventStore | None = None,
        security_settings: TransportSecuritySettings | None = None,
        retry_interval: int | None = None,
        *,
        app: Server[Any] | None = None,
        lifespan_state: Any = None,
    ) -> None:
        """Initialize a new StreamableHTTP server transport.

        Args:
            mcp_session_id: Optional session identifier for this connection.
                            Must contain only visible ASCII characters (0x21-0x7E).
            is_json_response_enabled: If True, return JSON responses for requests
                                    instead of SSE streams. Default is False.
            event_store: Event store for resumability support. If provided,
                        resumability will be enabled, allowing clients to
                        reconnect and resume messages.
            security_settings: Optional security settings for DNS rebinding protection.
            retry_interval: Retry interval in milliseconds to suggest to clients in SSE
                           retry field. When set, the server will send a retry field in
                           SSE priming events to control client reconnection timing for
                           polling behavior. Only used when event_store is provided.
            app: The `Server` whose handlers serve this session's requests. Only
                the `StreamableHTTPSessionManager` need supply this.
            lifespan_state: The server's already-entered lifespan output, shared
                across every session by the manager.

        Raises:
            ValueError: If the session ID contains invalid characters.
        """
        if mcp_session_id is not None and not SESSION_ID_PATTERN.fullmatch(mcp_session_id):
            raise ValueError("Session ID must only contain visible ASCII characters (0x21-0x7E)")

        self.mcp_session_id = mcp_session_id
        self.is_json_response_enabled = is_json_response_enabled
        self._event_store = event_store
        self._security = TransportSecurityMiddleware(security_settings)
        self._retry_interval = retry_interval
        self._app = app
        self._lifespan_state = lifespan_state
        self._terminated = False
        # Idle timeout cancel scope; managed by the session manager.
        self.idle_scope: anyio.CancelScope | None = None
        # Correlates server-to-client requests with the responses the client
        # POSTs back, and lets `notifications/cancelled` find in-flight handlers.
        self._corr: RequestCorrelator[_HTTPRequestDispatchContext] = RequestCorrelator()
        # Stream ids handed to the event store are minted here, in this
        # session's own namespace: distinct from anything a client can name
        # and unshared with other sessions on a common store. Stateless
        # transports (one per request) get a fresh scope each.
        self._stream_scope = mcp_session_id if mcp_session_id is not None else uuid4().hex
        # The standalone GET stream: server-initiated messages related to no request.
        self._standalone = _MessageChannel(f"{self._stream_scope}:{GET_STREAM_KEY}", event_store)
        # In-flight request streams, keyed by their event-store stream id
        # (`close_sse_stream()` and `Last-Event-ID` replay both look up here).
        self._streams: dict[StreamId, _MessageChannel] = {}
        # While an `initialize` is being served, other requests wait for its
        # commit: the handshake orders before every later request on the wire.
        self._initializing: anyio.Event | None = None
        # Session-scoped task group for request handlers (stateful mode). Handlers
        # outlive the HTTP request that started them: a dropped connection does
        # not cancel a 2025-era request (the client cancels explicitly).
        self._task_group: anyio.abc.TaskGroup | None = None
        # Whether session-bound work may still be scheduled. Cleared the moment
        # the session starts to end - explicit terminate, idle timeout, or
        # manager shutdown - before the task group drains its running handlers.
        self._accepting = True
        self._closed_event = anyio.Event()
        # The stateful session's connection state and handler kernel; stateless
        # mode builds a born-ready connection per request instead.
        self._connection: Connection | None = None
        self._runner: ServerRunner[Any] | None = None
        if app is not None and mcp_session_id is not None:
            outbound = _StandaloneOutbound(self._corr, self._standalone)
            self._connection = Connection.for_loop(outbound, session_id=mcp_session_id)
            self._runner = ServerRunner(app, self._connection, lifespan_state)

    @property
    def is_terminated(self) -> bool:
        """Check if this transport has been explicitly terminated."""
        return self._terminated

    def _owns_stream(self, stream_id: StreamId) -> bool:
        """Whether an event-store stream id was minted by this transport (this session)."""
        return stream_id == self._standalone.stream_id or stream_id.startswith(f"{self._stream_scope}:request:")

    def _request_stream_id(self, request_id: RequestId) -> StreamId:
        """The event-store stream id for one request's response stream.

        Minted in this session's namespace with a `request:` infix, so it is
        neither reachable from another session sharing the store nor equal to
        the standalone stream's id, whatever the client picks as request id.
        """
        return f"{self._stream_scope}:request:{request_id}"

    def close_sse_stream(self, request_id: RequestId) -> None:
        """Close SSE connection for a specific request without terminating the stream.

        This method closes the HTTP connection for the specified request, triggering
        client reconnection. Events continue to be stored in the event store and will
        be replayed when the client reconnects with Last-Event-ID.

        Use this to implement polling behavior during long-running operations -
        the client will reconnect after the retry interval specified in the priming event.

        Args:
            request_id: The request ID whose SSE stream should be closed.

        Note:
            This is a no-op if there is no active stream for the request ID.
            Requires event_store to be configured for events to be stored during
            the disconnect.
        """
        channel = self._streams.get(self._request_stream_id(request_id))
        if channel is not None:
            channel.detach()

    def close_standalone_sse_stream(self) -> None:
        """Close the standalone GET SSE stream, triggering client reconnection.

        This method closes the HTTP connection for the standalone GET stream used
        for unsolicited server-to-client notifications. The client SHOULD reconnect
        with Last-Event-ID to resume receiving notifications.

        Use this to implement polling behavior for the notification stream -
        the client will reconnect after the retry interval specified in the priming event.

        Note:
            This is a no-op if there is no active standalone SSE stream.
            Requires event_store to be configured for events to be stored during
            the disconnect.
        """
        self._standalone.detach()

    async def run(self, *, task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        """Host this session's request-handler tasks until the session is terminated.

        Request handlers run here rather than inside the HTTP request that
        started them, so a client that drops a connection does not cancel its
        request (per the 2025-era transport spec). Returns after `terminate()`;
        cancelling it (server shutdown or the idle timeout) cancels the
        handlers and tears the connection down.
        """
        self._require_app()
        connection = self._connection
        assert connection is not None, "a session-bound transport always has a connection"
        try:
            async with anyio.create_task_group() as tg:
                self._task_group = tg
                task_status.started()
                try:
                    await self._closed_event.wait()
                finally:
                    # However the session ends, stop taking work before the
                    # task group drains the handlers already running.
                    self._accepting = False
                tg.cancel_scope.cancel()
        finally:
            self._task_group = None
            # By now every request handler has finished and released its own
            # channel; end the standalone stream and wake anything awaiting a
            # client answer (runs on termination and manager shutdown alike).
            self._standalone.close()
            self._corr.close()
            await aclose_shielded(connection)

    def _build_message_metadata(
        self,
        request: Request,
        request_id: RequestId,
        protocol_version: str,
        *,
        channel: _MessageChannel | None = None,
    ) -> ServerMessageMetadata:
        """Build the per-request metadata the handler kernel lifts onto its request context.

        The close_sse_stream callbacks are only provided when the client supports
        resumability (protocol version >= 2025-11-25). Old clients can't resume if
        the stream is closed early because they didn't receive a priming event.
        With the request's `channel`, the metadata also carries the hook that
        terminates a request settling without a response on this era's wire.
        """
        on_request_unanswered = (
            partial(self._settle_unanswered_request, channel, request_id) if channel is not None else None
        )
        if self._event_store and is_version_at_least(protocol_version, "2025-11-25"):

            async def close_stream_callback() -> None:
                self.close_sse_stream(request_id)

            async def close_standalone_stream_callback() -> None:
                self.close_standalone_sse_stream()

            return ServerMessageMetadata(
                request_context=request,
                close_sse_stream=close_stream_callback,
                close_standalone_sse_stream=close_standalone_stream_callback,
                on_request_unanswered=on_request_unanswered,
            )
        return ServerMessageMetadata(request_context=request, on_request_unanswered=on_request_unanswered)

    def _transport_context(self, request: Request, *, can_send_request: bool) -> TransportContext:
        return TransportContext(kind="streamable-http", can_send_request=can_send_request, headers=request.headers)

    async def _mint_priming_event(self, stream_id: StreamId, protocol_version: str) -> SSEEvent | None:
        """Store the priming cursor for `stream_id` and return its SSE wire form.

        Called before the request is dispatched so the priming row precedes
        anything the handler can store for this stream. Returns `None` when
        no event store is configured or the client predates 2025-11-25
        (older clients cannot parse the empty-data event).
        """
        if not self._event_store:
            return None
        if not is_version_at_least(protocol_version, "2025-11-25"):
            return None
        priming_event_id = await self._event_store.store_event(stream_id, None)
        priming_event: SSEEvent = {"id": priming_event_id, "data": ""}
        if self._retry_interval is not None:
            priming_event["retry"] = self._retry_interval
        return priming_event

    def _create_error_response(
        self,
        error_message: str,
        status_code: HTTPStatus,
        error_code: int = INVALID_REQUEST,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """Create an error response with a simple string message."""
        response_headers = {"Content-Type": CONTENT_TYPE_JSON}
        if headers:
            response_headers.update(headers)

        if self.mcp_session_id:
            response_headers[MCP_SESSION_ID_HEADER] = self.mcp_session_id

        # Return a properly formatted JSON error response
        error_response = JSONRPCError(
            jsonrpc="2.0",
            id=None,
            error=ErrorData(code=error_code, message=error_message),
        )

        return Response(
            error_response.model_dump_json(by_alias=True, exclude_unset=True),
            status_code=status_code,
            headers=response_headers,
        )

    def _create_json_response(
        self,
        response_message: JSONRPCMessage | None,
        status_code: HTTPStatus = HTTPStatus.OK,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """Create a JSON response from a JSONRPCMessage."""
        response_headers = {"Content-Type": CONTENT_TYPE_JSON}
        if headers:
            response_headers.update(headers)  # pragma: no cover

        if self.mcp_session_id:
            response_headers[MCP_SESSION_ID_HEADER] = self.mcp_session_id

        return Response(
            response_message.model_dump_json(by_alias=True, exclude_unset=True) if response_message else None,
            status_code=status_code,
            headers=response_headers,
        )

    def _get_session_id(self, request: Request) -> str | None:
        """Extract the session ID from request headers."""
        return request.headers.get(MCP_SESSION_ID_HEADER)

    def _create_event_data(self, event_message: EventMessage) -> SSEEvent:
        """Create event data dictionary from an EventMessage."""
        event_data = {
            "event": "message",
            "data": event_message.message.model_dump_json(by_alias=True, exclude_unset=True),
        }

        # If an event ID was provided, include it
        if event_message.event_id:
            event_data["id"] = event_message.event_id

        return event_data

    def _sse_headers(self) -> dict[str, str]:
        return {
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "Content-Type": CONTENT_TYPE_SSE,
            **({MCP_SESSION_ID_HEADER: self.mcp_session_id} if self.mcp_session_id else {}),
        }

    async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Application entry point that handles all HTTP requests.

        Raises:
            RuntimeError: The transport was constructed without a server to
                dispatch to (`app`); it is created and driven by
                `StreamableHTTPSessionManager`.
        """
        self._require_app()
        request = Request(scope, receive)

        # Validate request headers for DNS rebinding protection
        is_post = request.method == "POST"
        error_response = await self._security.validate_request(request, is_post=is_post)
        if error_response:
            await error_response(scope, receive, send)
            return

        if self._terminated:
            # If the session has been terminated, return 404 Not Found
            response = self._create_error_response(
                "Not Found: Session has been terminated",
                HTTPStatus.NOT_FOUND,
            )
            await response(scope, receive, send)
            return

        if request.method == "POST":
            await self._handle_post_request(scope, request, receive, send)
        elif request.method == "GET":
            await self._handle_get_request(request, send)
        elif request.method == "DELETE":
            await self._handle_delete_request(request, send)
        else:
            await self._handle_unsupported_request(request, send)

    def _check_content_type(self, request: Request) -> bool:
        """Check if the request has the correct Content-Type."""
        content_type = request.headers.get("content-type", "")
        content_type_parts = [part.strip() for part in content_type.split(";")[0].split(",")]

        return any(part == CONTENT_TYPE_JSON for part in content_type_parts)

    async def _validate_accept_header(self, request: Request, scope: Scope, send: Send) -> bool:
        """Validate Accept header based on response mode. Returns True if valid."""
        has_json, has_sse = check_accept_headers(request)
        if self.is_json_response_enabled:
            # For JSON-only responses, only require application/json
            if not has_json:
                response = self._create_error_response(
                    "Not Acceptable: Client must accept application/json",
                    HTTPStatus.NOT_ACCEPTABLE,
                )
                await response(scope, request.receive, send)
                return False
        # For SSE responses, require both content types
        elif not (has_json and has_sse):
            response = self._create_error_response(
                "Not Acceptable: Client must accept both application/json and text/event-stream",
                HTTPStatus.NOT_ACCEPTABLE,
            )
            await response(scope, request.receive, send)
            return False
        return True

    def _require_app(self) -> Server[Any]:
        if self._app is None:
            raise RuntimeError(
                "StreamableHTTPServerTransport is not bound to a server; "
                "it is created and driven by StreamableHTTPSessionManager"
            )
        return self._app

    async def _handle_post_request(self, scope: Scope, request: Request, receive: Receive, send: Send) -> None:
        """Handle POST requests containing JSON-RPC messages."""
        try:
            # Validate Accept header
            if not await self._validate_accept_header(request, scope, send):
                return

            # Validate Content-Type
            if not self._check_content_type(request):  # pragma: no cover
                response = self._create_error_response(
                    "Unsupported Media Type: Content-Type must be application/json",
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                )
                await response(scope, receive, send)
                return

            # Parse the body - only read it once
            body = await request.body()

            try:
                raw_message = pydantic_core.from_json(body)
            except ValueError as e:
                response = self._create_error_response(f"Parse error: {str(e)}", HTTPStatus.BAD_REQUEST, PARSE_ERROR)
                await response(scope, receive, send)
                return

            try:
                message = jsonrpc_message_adapter.validate_python(raw_message, by_name=False)
            except ValidationError as e:
                response = self._create_error_response(
                    f"Validation error: {str(e)}",
                    HTTPStatus.BAD_REQUEST,
                    INVALID_PARAMS,
                )
                await response(scope, receive, send)
                return

            # Check if this is an initialization request
            is_initialization_request = isinstance(message, JSONRPCRequest) and message.method == "initialize"

            if is_initialization_request:
                # Check if the server already has an established session
                if self.mcp_session_id:
                    # Check if request has a session ID
                    request_session_id = self._get_session_id(request)

                    # If request has a session ID but doesn't match, return 404
                    if request_session_id and request_session_id != self.mcp_session_id:  # pragma: no cover
                        response = self._create_error_response(
                            "Not Found: Invalid or expired session ID",
                            HTTPStatus.NOT_FOUND,
                        )
                        await response(scope, receive, send)
                        return
            elif not await self._validate_request_headers(request, send):
                return

            # For notifications and responses only, return 202 Accepted
            if not isinstance(message, JSONRPCRequest):
                # Create response object and send it
                response = self._create_json_response(
                    None,
                    HTTPStatus.ACCEPTED,
                )
                try:
                    await response(scope, receive, send)
                finally:
                    # A body that arrived in full is delivered even when the
                    # 202 could not be (the client dropped after sending it):
                    # a lost ack must not lose an answer or a cancellation.
                    await self._deliver_client_message(request, message)
                return

            # Extract protocol version for priming event decision.
            # For initialize requests, get from request params.
            # For other requests, get from header (already validated).
            protocol_version = (
                str(message.params.get("protocolVersion", DEFAULT_NEGOTIATED_VERSION))
                if is_initialization_request and message.params
                else request.headers.get(MCP_PROTOCOL_VERSION_HEADER, DEFAULT_NEGOTIATED_VERSION)
            )

            await self._serve_request(scope, request, receive, send, message, protocol_version)

        except Exception:
            logger.exception("Error handling POST request")
            response = self._create_error_response(
                "Error handling POST request",
                HTTPStatus.INTERNAL_SERVER_ERROR,
                INTERNAL_ERROR,
            )
            await response(scope, receive, send)
            return

    def _session_runner(self) -> ServerRunner[Any]:
        """The stateful session's handler kernel; built with the transport's server binding."""
        assert self._runner is not None
        return self._runner

    def _stateless_runner(self, request: Request) -> ServerRunner[Any]:
        """A born-ready, no-back-channel kernel for one stateless request.

        The `MCP-Protocol-Version` header (or the spec's default when it is
        absent) seeds `ctx.protocol_version`; there is no handshake to negotiate it.
        """
        protocol_version = request.headers.get(MCP_PROTOCOL_VERSION_HEADER, DEFAULT_NEGOTIATED_VERSION)
        connection = Connection.from_envelope(protocol_version, None, None)
        return ServerRunner(self._require_app(), connection, self._lifespan_state)

    async def _deliver_client_message(
        self, request: Request, message: JSONRPCNotification | JSONRPCResponse | JSONRPCError
    ) -> None:
        """Handle a POSTed response (to a server-initiated request) or notification, after the 202."""
        if isinstance(message, JSONRPCResponse):
            self._corr.resolve(message.id, message.result)
            return
        if isinstance(message, JSONRPCError):
            self._corr.resolve(message.id, message.error)
            return
        if message.method == "notifications/cancelled":
            self._corr.peer_cancel(cancelled_request_id_from_params(message.params), interrupt=True)
        elif message.method == "notifications/progress":
            delivery = self._corr.progress_callback(message.params)
            if delivery is not None:
                fn, progress, total, note = delivery
                await self._spawn_or_run(fn, progress, total, note)
        if self.mcp_session_id is None:
            runner = self._stateless_runner(request)
            connection = runner.connection
        else:
            runner = self._session_runner()
            connection = None
        dctx = _HTTPRequestDispatchContext(
            transport=self._transport_context(request, can_send_request=self._can_send_request),
            _corr=self._corr,
            _channel=self._standalone,
            _request_id=None,
            message_metadata=ServerMessageMetadata(request_context=request),
        )

        async def _run_notification() -> None:
            # `on_notify` contains handler exceptions itself, so a crashing
            # notification handler cannot take the session down.
            try:
                await runner.on_notify(dctx, message.method, message.params)
            finally:
                if connection is not None:
                    await aclose_shielded(connection)

        await self._spawn_or_run(_run_notification)

    @property
    def _can_send_request(self) -> bool:
        """Whether a request handler on this transport has a back-channel for server-to-client requests.

        JSON-response mode has none: the request's response is one JSON body,
        so a nested elicitation or sampling request has no stream to ride.
        Stateless mode additionally lacks a session, so no POST of the client's
        answer could be correlated back to a waiting handler.
        """
        return self.mcp_session_id is not None and not self.is_json_response_enabled

    async def _spawn_or_run(self, fn: Callable[..., Awaitable[None]], *args: Any) -> None:
        """Run `fn(*args)`: on the session task group when session-bound, inline when stateless.

        A session-bound transport whose session has ended drops the work: the
        session is being torn down, so no handler may run against it.
        """
        if self.mcp_session_id is None:
            await fn(*args)
            return
        tg = self._task_group
        if tg is None or not self._accepting:
            logger.debug("dropped work for ended session %s", self.mcp_session_id)
            return
        tg.start_soon(fn, *args)

    async def _serve_request(
        self,
        scope: Scope,
        request: Request,
        receive: Receive,
        send: Send,
        message: JSONRPCRequest,
        protocol_version: str,
    ) -> None:
        """Dispatch one POSTed JSON-RPC request and stream its response."""
        request_id = message.id
        stream_id = self._request_stream_id(request_id)
        stateful = self.mcp_session_id is not None

        # A request other than `initialize` waits for a handshake in progress
        # to commit: over one stream the read loop parked to guarantee this;
        # over HTTP the requests are concurrent, so the transport keeps the
        # same order explicitly. This handshake's gate exists before its
        # first await.
        initialize_gate: anyio.Event | None = None
        if stateful and message.method == "initialize":
            initialize_gate = anyio.Event()
            self._initializing = initialize_gate
        elif stateful and (gate := self._initializing) is not None:
            await gate.wait()

        # From here the gate must be released whatever becomes of this
        # request: by the handler task once it exists, else by this frame.
        handler_started = False
        try:
            handler_started = await self._start_request(
                scope, request, receive, send, message, protocol_version, stream_id, initialize_gate
            )
        finally:
            if initialize_gate is not None and not handler_started:
                self._release_initialize_gate(initialize_gate)

    def _release_initialize_gate(self, gate: anyio.Event) -> None:
        """Let the requests held behind this handshake proceed, and clear it if still current."""
        gate.set()
        if self._initializing is gate:
            self._initializing = None

    async def _start_request(
        self,
        scope: Scope,
        request: Request,
        receive: Receive,
        send: Send,
        message: JSONRPCRequest,
        protocol_version: str,
        stream_id: StreamId,
        initialize_gate: anyio.Event | None,
    ) -> bool:
        """Register and start one request; returns whether a handler task took over its lifecycle."""
        request_id = message.id
        stateful = self.mcp_session_id is not None

        # Mint the priming event before any per-request state exists:
        # `EventStore.store_event` is user code and may raise, in which
        # case the outer handler returns a 500 with nothing to clean up.
        # Still strictly precedes dispatch, so storage order == wire order.
        priming_event = (
            None if self.is_json_response_enabled else await self._mint_priming_event(stream_id, protocol_version)
        )

        # The session may have ended (DELETE, idle timeout, manager shutdown)
        # while this request was suspended above; a session-bound transport must
        # refuse the request instead of running it against a dead session. No
        # await from here to the dispatch, so the answer holds when we act on it.
        session_task_group = self._task_group
        if stateful and (not self._accepting or session_task_group is None):
            response = self._create_error_response(
                "Not Found: Session has been terminated",
                HTTPStatus.NOT_FOUND,
            )
            await response(scope, receive, send)
            return False

        channel = _MessageChannel(stream_id, self._event_store)
        self._streams[stream_id] = channel
        # Attach the response's writer before the handler starts, so nothing
        # the handler emits early lands on an unattached channel.
        reader = None if self.is_json_response_enabled else channel.attach()

        if stateful:
            runner = self._session_runner()
            connection = None
        else:
            runner = self._stateless_runner(request)
            connection = runner.connection
        dctx = _HTTPRequestDispatchContext(
            transport=self._transport_context(request, can_send_request=self._can_send_request),
            _corr=self._corr,
            _channel=channel,
            _request_id=request_id,
            message_metadata=self._build_message_metadata(request, request_id, protocol_version, channel=channel),
            _progress_token=progress_token_from_params(message.params),
        )
        cancel_scope = anyio.CancelScope()
        self._corr.enter_inbound(request_id, cancel_scope, dctx)

        async def _run_handler() -> None:
            try:
                # `serve_inbound` contains handler exceptions and `channel.write`
                # never raises, so this task always completes on its own.
                await self._corr.serve_inbound(
                    request_id,
                    dctx,
                    cancel_scope,
                    partial(runner.on_request, dctx, message.method, message.params),
                    write_result=partial(self._write_result, channel, request_id),
                    write_error=partial(self._write_error, channel, request_id),
                    settle_unanswered=dctx.message_metadata.on_request_unanswered if dctx.message_metadata else None,
                )
            finally:
                if initialize_gate is not None:
                    self._release_initialize_gate(initialize_gate)
                # The channel stays registered until the handler is done, so a
                # `Last-Event-ID` reconnect can re-attach while it still runs.
                channel.close()
                if self._streams.get(stream_id) is channel:
                    del self._streams[stream_id]
                if connection is not None:
                    await aclose_shielded(connection)

        if session_task_group is not None:
            # Session-scoped: the handler outlives this HTTP request. A client
            # that drops the connection is not cancelling the request (it may
            # resume via Last-Event-ID); it cancels by POSTing notifications/cancelled.
            session_task_group.start_soon(_run_handler)
            if reader is None:
                await self._respond_json(scope, receive, send, channel)
            else:
                await self._respond_sse(scope, receive, send, channel, reader, priming_event)
        else:
            # Stateless: this request is the whole connection, so the handler's
            # lifetime is the response's - it is cancelled once the response
            # ends (result delivered, or the client went away).
            async with anyio.create_task_group() as tg:
                tg.start_soon(_run_handler)
                if reader is None:
                    await self._respond_json(scope, receive, send, channel)
                else:
                    await self._respond_sse(scope, receive, send, channel, reader, priming_event)
                tg.cancel_scope.cancel()
        return True

    async def _settle_unanswered_request(self, channel: _MessageChannel, request_id: RequestId) -> None:
        """Terminate a request that settled without a response (e.g. it was cancelled).

        The 2025-era wire ends a request's stream only with a response for its
        id - and stores that response so a resuming client's replay terminates
        too - so this era answers a cancelled request with `REQUEST_CANCELLED`
        where the dispatch layer itself stays silent (the 2026 transports MUST
        NOT answer). It goes through the request's own ordered channel, so it
        cannot overtake anything already queued for it.
        """
        await self._write_error(channel, request_id, ErrorData(code=REQUEST_CANCELLED, message="Request cancelled"))

    async def _write_result(self, channel: _MessageChannel, request_id: RequestId, result: dict[str, Any]) -> None:
        await channel.write(JSONRPCResponse(jsonrpc="2.0", id=request_id, result=result))

    async def _write_error(self, channel: _MessageChannel, request_id: RequestId, error: ErrorData) -> None:
        await channel.write(JSONRPCError(jsonrpc="2.0", id=request_id, error=error))

    async def _respond_json(self, scope: Scope, receive: Receive, send: Send, channel: _MessageChannel) -> None:
        """Wait for the request's terminal message and send it as one JSON body."""
        await channel.finished.wait()
        response_message = channel.terminal
        if response_message is not None:
            response = self._create_json_response(response_message)
        elif self._terminated:
            # The session ended underneath the request; it gets the same
            # answer every request to a terminated session gets.
            response = self._create_error_response(
                "Not Found: Session has been terminated",
                HTTPStatus.NOT_FOUND,
            )
        else:  # pragma: lax no cover
            # The request finished without recording an answer (a wedged store
            # can outlast the shutdown write bound). Nothing to send but a 500.
            logger.error("No response message received before stream closed")
            response = self._create_error_response(
                "Error processing request: No response received",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        await response(scope, receive, send)

    async def _respond_sse(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        channel: _MessageChannel,
        reader: MemoryObjectReceiveStream[EventMessage] | None,
        priming_event: SSEEvent | None,
    ) -> None:
        """Stream the request's channel as this POST's SSE response, until the response frame passes."""
        assert reader is not None, "a freshly created request channel always attaches"
        await self._run_sse_response(
            scope, receive, send, partial(self._pump_channel, channel, reader, priming_event, stop_at_response=True)
        )
        # The client is gone (disconnect or delivered response): detach so the
        # handler carries on writing to the store alone.
        channel.detach(reader)

    async def _run_sse_response(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        data_sender: Callable[[MemoryObjectSendStream[SSEEvent]], Coroutine[Any, Any, None]],
    ) -> None:
        """Run one SSE response fed by `data_sender`, the single containment site for all of them.

        `data_sender(sse_send)` writes the events (a channel pump, or a replay
        followed by a pump). An error escaping the started response is logged
        here and goes no further: the response already began, so nothing may
        answer this request a second time.
        """
        sse_send, sse_recv = anyio.create_memory_object_stream[SSEEvent](0)
        response = EventSourceResponse(
            content=sse_recv,
            data_sender_callable=partial(data_sender, sse_send),
            headers=self._sse_headers(),
        )
        try:
            await response(scope, receive, send)
        except Exception:  # pragma: lax no cover
            logger.exception("Error in SSE response")
        finally:
            await sse_send.aclose()
            await sse_recv.aclose()

    async def _pump_channel(
        self,
        channel: _MessageChannel,
        reader: MemoryObjectReceiveStream[EventMessage],
        priming_event: SSEEvent | None,
        sse_send: MemoryObjectSendStream[SSEEvent],
        *,
        stop_at_response: bool,
    ) -> None:
        """Forward one attachment of `channel` onto an SSE response's event queue.

        Runs as sse-starlette's data sender, so a client disconnect cancels it
        along with the response; the `finally` detaches this attachment (never
        a newer one that a `Last-Event-ID` reconnect may have installed).
        """
        try:
            async with sse_send, reader:
                if priming_event is not None:
                    await sse_send.send(priming_event)
                async for event_message in reader:
                    await sse_send.send(self._create_event_data(event_message))
                    if stop_at_response and isinstance(event_message.message, JSONRPCResponse | JSONRPCError):
                        break
        finally:
            logger.debug("Closing SSE writer")
            channel.detach(reader)

    async def _handle_get_request(self, request: Request, send: Send) -> None:
        """Handle GET request to establish SSE.

        This allows the server to communicate to the client without the client
        first sending data via HTTP POST. The server can send JSON-RPC requests
        and notifications on this stream.
        """
        # Validate Accept header - must include text/event-stream
        _, has_sse = check_accept_headers(request)

        if not has_sse:
            response = self._create_error_response(
                "Not Acceptable: Client must accept text/event-stream",
                HTTPStatus.NOT_ACCEPTABLE,
            )
            await response(request.scope, request.receive, send)
            return

        if not await self._validate_request_headers(request, send):
            return

        # Handle resumability: check for Last-Event-ID header
        if self._event_store and (last_event_id := request.headers.get(LAST_EVENT_ID_HEADER)):
            await self._replay_events(last_event_id, request, send)
            return

        # Check if we already have an active GET stream
        if self._standalone.attached:
            response = self._create_error_response(
                "Conflict: Only one SSE stream is allowed per session",
                HTTPStatus.CONFLICT,
            )
            await response(request.scope, request.receive, send)
            return

        reader = self._standalone.attach()
        if reader is None:  # pragma: lax no cover
            # The session was terminated between the entry check and here.
            response = self._create_error_response(
                "Not Found: Session has been terminated",
                HTTPStatus.NOT_FOUND,
            )
            await response(request.scope, request.receive, send)
            return
        try:
            # This will send headers immediately and establish the SSE connection
            await self._run_sse_response(
                request.scope,
                request.receive,
                send,
                partial(self._pump_channel, self._standalone, reader, None, stop_at_response=False),
            )
        finally:
            self._standalone.detach(reader)

    async def _handle_delete_request(self, request: Request, send: Send) -> None:
        """Handle DELETE requests for explicit session termination."""
        # Validate session ID
        if not self.mcp_session_id:  # pragma: no cover
            # If no session ID set, return Method Not Allowed
            response = self._create_error_response(
                "Method Not Allowed: Session termination not supported",
                HTTPStatus.METHOD_NOT_ALLOWED,
            )
            await response(request.scope, request.receive, send)
            return

        if not await self._validate_request_headers(request, send):  # pragma: no cover
            return

        await self.terminate()

        response = self._create_json_response(
            None,
            HTTPStatus.OK,
        )
        await response(request.scope, request.receive, send)

    async def terminate(self) -> None:
        """Terminate the current session, closing all streams.

        Once terminated, all requests with this session ID will receive 404 Not Found.
        """

        self._terminated = True
        self._accepting = False
        logger.info(f"Terminating session: {self.mcp_session_id}")

        # Close every open response stream, wake anything awaiting a
        # client answer, and cancel in-flight handlers.
        for channel in list(self._streams.values()):
            channel.close()
        self._streams.clear()
        self._standalone.close()
        self._corr.close()
        self._corr.cancel_all_inbound()
        # Release the session task, which cancels any handler still running
        # and closes the connection's exit stack.
        self._closed_event.set()

    async def _handle_unsupported_request(self, request: Request, send: Send) -> None:
        """Handle unsupported HTTP methods."""
        headers = {
            "Content-Type": CONTENT_TYPE_JSON,
            "Allow": "GET, POST, DELETE",
        }
        if self.mcp_session_id:  # pragma: no branch
            headers[MCP_SESSION_ID_HEADER] = self.mcp_session_id

        response = self._create_error_response(
            "Method Not Allowed",
            HTTPStatus.METHOD_NOT_ALLOWED,
            headers=headers,
        )
        await response(request.scope, request.receive, send)

    async def _validate_request_headers(self, request: Request, send: Send) -> bool:
        # Protocol-version validation lives in the manager's era-routing: only
        # values in `HANDSHAKE_PROTOCOL_VERSIONS` (or no header at all) reach
        # this transport, so the legacy version-gate is gone.
        return await self._validate_session(request, send)

    async def _validate_session(self, request: Request, send: Send) -> bool:
        """Validate the session ID in the request."""
        if not self.mcp_session_id:
            # If we're not using session IDs, return True
            return True

        # Get the session ID from the request headers
        request_session_id = self._get_session_id(request)

        # If no session ID provided but required, return error
        if not request_session_id:
            response = self._create_error_response(
                "Bad Request: Missing session ID",
                HTTPStatus.BAD_REQUEST,
            )
            await response(request.scope, request.receive, send)
            return False

        # If session ID doesn't match, return error
        if request_session_id != self.mcp_session_id:  # pragma: no cover
            response = self._create_error_response(
                "Not Found: Invalid or expired session ID",
                HTTPStatus.NOT_FOUND,
            )
            await response(request.scope, request.receive, send)
            return False

        return True

    async def _replay_events(self, last_event_id: str, request: Request, send: Send) -> None:
        """Replays events that would have been sent after the specified event ID.

        Only used when resumability is enabled.
        """
        event_store = self._event_store
        if not event_store:
            return  # pragma: no cover

        try:
            # The manager only routes supported (or absent) header values to this transport
            replay_protocol_version = request.headers.get(MCP_PROTOCOL_VERSION_HEADER, DEFAULT_NEGOTIATED_VERSION)

            async def replay_then_tail(sse_send: MemoryObjectSendStream[SSEEvent]) -> None:
                try:
                    async with sse_send:
                        # Buffer the replay until the store names its stream: the
                        # event id came from the client, so only a stream in this
                        # session's namespace is allowed onto the wire.
                        replayed: list[EventMessage] = []

                        async def collect_event(event_message: EventMessage) -> None:
                            replayed.append(event_message)

                        # Replay past events and get the stream ID
                        stream_id = await event_store.replay_events_after(last_event_id, collect_event)
                        if not stream_id:
                            return
                        if not self._owns_stream(stream_id):
                            logger.warning(
                                "Refusing to replay foreign stream %r on session %s", stream_id, self.mcp_session_id
                            )
                            return
                        for event_message in replayed:
                            await sse_send.send(self._create_event_data(event_message))

                        # Live-tail the stream if it is still open and no response
                        # is currently attached to it: the `close_sse_stream()`
                        # polling reconnect, and a client resuming a dropped connection.
                        if stream_id == self._standalone.stream_id:
                            channel = self._standalone
                        else:
                            channel = self._streams.get(stream_id)
                        if channel is None or channel.attached:
                            return

                        # Attach first, so anything the still-running request emits
                        # from here on is buffered for this response rather than
                        # only stored. The replay→live-tail ordering window (frames
                        # stored between the replay read and the attach) is pre-existing
                        # and tracked separately.
                        reader = channel.attach()
                        if reader is None:
                            # The stream ended (session terminated) while the store
                            # was read; there is nothing left to tail.
                            return
                        try:
                            # Prime the resumed connection so the client sees the
                            # stream is re-registered.
                            priming_event = await self._mint_priming_event(stream_id, replay_protocol_version)

                            # Forward messages to SSE: a request's stream ends after
                            # its response frame; the standalone stream carries no
                            # response and tails until the client leaves again.
                            await self._pump_channel(
                                channel,
                                reader,
                                priming_event,
                                sse_send,
                                stop_at_response=channel is not self._standalone,
                            )
                        finally:
                            channel.detach(reader)
                            # The pump closes the reader it drained; this covers a
                            # priming failure that never handed the reader over.
                            reader.close()
                except Exception:
                    # `replay_events_after` is user code; a failing replay ends this response only.
                    logger.exception("Error in replay sender")

            # Create and start EventSourceResponse
            await self._run_sse_response(request.scope, request.receive, send, replay_then_tail)

        except Exception:  # pragma: lax no cover
            logger.exception("Error replaying events")
            response = self._create_error_response(
                "Error replaying events",
                HTTPStatus.INTERNAL_SERVER_ERROR,
                INTERNAL_ERROR,
            )
            await response(request.scope, request.receive, send)
