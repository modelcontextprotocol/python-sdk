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
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Final

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

# Session ID validation pattern (visible ASCII characters ranging from 0x21 to 0x7E)
# Pattern ensures entire string contains only valid characters by using ^ and $ anchors
SESSION_ID_PATTERN = re.compile(r"^[\x21-\x7E]+$")

# Streamable HTTP transport kind for `TransportContext.kind`.
STREAMABLE_HTTP_KIND = "streamable-http"

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
            The stream ID of the replayed events, or None if no events were found.
        """
        pass  # pragma: no cover


class _MessageChannel:
    """One SSE stream's outbound messages: a request's response stream, or the standalone GET stream.

    Every message is first offered to the `EventStore` (so a client that
    drops the connection can resume via `Last-Event-ID`), then forwarded to
    the SSE response currently attached to the channel, if any. With no
    response attached the message is only stored (or, without a store,
    dropped with a debug log) - the client can reconnect and replay.
    """

    def __init__(self, stream_id: StreamId, event_store: EventStore | None) -> None:
        self.stream_id = stream_id
        self._event_store = event_store
        self._writer: MemoryObjectSendStream[EventMessage] | None = None
        self._closed = False
        self.terminal: JSONRPCResponse | JSONRPCError | None = None
        """The terminal outcome once the request this channel serves has finished."""
        self.finished = anyio.Event()
        """Set once `terminal` is recorded (or the channel is closed by termination)."""

    @property
    def attached(self) -> bool:
        """Whether an SSE response is currently draining this channel."""
        return self._writer is not None

    async def write(self, message: JSONRPCMessage) -> None:
        """Store-then-forward one outbound message. Never raises for a dropped connection."""
        if self._closed:
            logger.debug("dropped message on closed stream %s", self.stream_id)
            return
        # Store the event if we have an event store,
        # regardless of whether a client is connected
        # messages will be replayed on the re-connect
        event_id: EventId | None = None
        if self._event_store is not None:
            event_id = await self._event_store.store_event(self.stream_id, message)
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
            return
        try:
            await writer.send(EventMessage(message, event_id))
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            # The SSE response went away between the attach check and the send.
            self._detach(writer)

    def attach(self) -> MemoryObjectReceiveStream[EventMessage]:
        """Attach a fresh SSE response and return the reader it drains.

        Callers check `attached` first where a second reader is an error
        (the standalone GET stream); re-attaching after a detach is how a
        `Last-Event-ID` reconnect resumes a live stream.
        """
        assert self._writer is None, "every attach site checks `attached` first"
        writer, reader = anyio.create_memory_object_stream[EventMessage](REQUEST_STREAM_BUFFER_SIZE)
        self._writer = writer
        return reader

    def detach(self, reader: MemoryObjectReceiveStream[EventMessage] | None = None) -> None:
        """Detach the current SSE response so the request can carry on without it.

        `reader` scopes the detach to one attachment: a stale response ending
        must not knock a newer (resumed) attachment off the channel.
        """
        writer = self._writer
        if writer is None:
            return
        if reader is not None and not self._is_writer_of(writer, reader):
            return
        self._detach(writer)

    def _is_writer_of(
        self, writer: MemoryObjectSendStream[EventMessage], reader: MemoryObjectReceiveStream[EventMessage]
    ) -> bool:
        # A memory-object stream pair shares one state object.
        return getattr(writer, "_state", None) is getattr(reader, "_state", None)

    def _detach(self, writer: MemoryObjectSendStream[EventMessage]) -> None:
        if self._writer is writer:
            self._writer = None
        writer.close()

    def close(self) -> None:
        """End the channel outright (session termination): detach and refuse further writes."""
        self._closed = True
        if self._writer is not None:
            self._detach(self._writer)
        self.finished.set()

    def finish(self) -> None:
        """The request is over: mark it finished and end any response still attached.

        Normally the terminal frame already ended the response; this covers a
        request whose terminal write never landed (e.g. the event store raised
        mid-stream), so the client sees the stream close rather than hanging.
        """
        self.finished.set()
        if self._writer is not None:
            self._detach(self._writer)


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

    async def send_cancel(request_id: RequestId, reason: str) -> None:
        await channel.write(_notification("notifications/cancelled", {"requestId": request_id, "reason": reason}))

    return await corr.call(
        method,
        params,
        opts,
        write_request=channel.write,
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
        # The standalone GET stream: server-initiated messages related to no request.
        self._standalone = _MessageChannel(GET_STREAM_KEY, event_store)
        # In-flight request streams, keyed by stream id (str of the request id),
        # so `close_sse_stream()` and `Last-Event-ID` replay can find them.
        self._channels: dict[StreamId, _MessageChannel] = {}
        # Session-scoped task group for request handlers (stateful mode). Handlers
        # outlive the HTTP request that started them: a dropped connection does
        # not cancel a 2025-era request (the client cancels explicitly).
        self._task_group: anyio.abc.TaskGroup | None = None
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
        stream_id = str(request_id)
        channel = self._standalone if stream_id == GET_STREAM_KEY else self._channels.get(stream_id)
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
                await self._closed_event.wait()
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
        self, request: Request, request_id: RequestId, protocol_version: str
    ) -> ServerMessageMetadata:
        """Build the per-request metadata the handler kernel lifts onto its request context.

        The close_sse_stream callbacks are only provided when the client supports
        resumability (protocol version >= 2025-11-25). Old clients can't resume if
        the stream is closed early because they didn't receive a priming event.
        """
        if self._event_store and is_version_at_least(protocol_version, "2025-11-25"):

            async def close_stream_callback() -> None:
                self.close_sse_stream(request_id)

            async def close_standalone_stream_callback() -> None:
                self.close_standalone_sse_stream()

            return ServerMessageMetadata(
                request_context=request,
                close_sse_stream=close_stream_callback,
                close_standalone_sse_stream=close_standalone_stream_callback,
            )
        return ServerMessageMetadata(request_context=request)

    def _transport_context(self, request: Request, *, can_send_request: bool) -> TransportContext:
        return TransportContext(kind=STREAMABLE_HTTP_KIND, can_send_request=can_send_request, headers=request.headers)

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
                await response(scope, receive, send)

                # Process the message after sending the response
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

        Stateless mode and JSON-response mode have none: a nested elicitation
        or sampling request has no stream to ride, and no POST of the client's
        answer could be correlated back to a session.
        """
        return self.mcp_session_id is not None and not self.is_json_response_enabled

    async def _spawn_or_run(self, fn: Callable[..., Awaitable[None]], *args: Any) -> None:
        """Run `fn(*args)` on the session task group if one is running, else inline."""
        tg = self._task_group
        if tg is not None:
            tg.start_soon(fn, *args)
        else:
            await fn(*args)

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
        stream_id = str(request_id)

        # Mint the priming event before any per-request state exists:
        # `EventStore.store_event` is user code and may raise, in which
        # case the outer handler returns a 500 with nothing to clean up.
        # Still strictly precedes dispatch, so storage order == wire order.
        priming_event = (
            None if self.is_json_response_enabled else await self._mint_priming_event(stream_id, protocol_version)
        )

        channel = _MessageChannel(stream_id, self._event_store)
        self._channels[stream_id] = channel
        # Attach the response's writer before the handler starts, so nothing
        # the handler emits early lands on an unattached channel.
        reader = None if self.is_json_response_enabled else channel.attach()

        if self.mcp_session_id is None:
            runner = self._stateless_runner(request)
            connection = runner.connection
        else:
            runner = self._session_runner()
            connection = None
        dctx = _HTTPRequestDispatchContext(
            transport=self._transport_context(request, can_send_request=self._can_send_request),
            _corr=self._corr,
            _channel=channel,
            _request_id=request_id,
            message_metadata=self._build_message_metadata(request, request_id, protocol_version),
            _progress_token=progress_token_from_params(message.params),
        )
        cancel_scope = anyio.CancelScope()
        self._corr.enter_inbound(request_id, cancel_scope, dctx)

        async def _run_handler() -> None:
            try:
                await self._corr.serve_inbound(
                    request_id,
                    dctx,
                    cancel_scope,
                    partial(runner.on_request, dctx, message.method, message.params),
                    write_result=partial(self._write_result, channel, request_id),
                    write_error=partial(self._write_error, channel, request_id),
                )
            except Exception:
                # `serve_inbound` contains handler exceptions itself; anything
                # escaping it is a channel write that raised (e.g. a broken
                # EventStore), which must cost this request, not the session.
                logger.exception("Error handling request %r", request_id)
            finally:
                # The channel stays registered until the handler is done, so a
                # `Last-Event-ID` reconnect can re-attach while it still runs.
                channel.finish()
                if self._channels.get(stream_id) is channel:
                    del self._channels[stream_id]
                if connection is not None:
                    await aclose_shielded(connection)

        if self._task_group is not None:
            # Session-scoped: the handler outlives this HTTP request. A client
            # that drops the connection is not cancelling the request (it may
            # resume via Last-Event-ID); it cancels by POSTing notifications/cancelled.
            self._task_group.start_soon(_run_handler)
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
        else:  # pragma: no cover
            # This shouldn't happen in normal operation
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
        reader: MemoryObjectReceiveStream[EventMessage],
        priming_event: SSEEvent | None,
    ) -> None:
        """Stream the request's channel as this POST's SSE response, until the response frame passes."""
        sse_send, sse_recv = anyio.create_memory_object_stream[SSEEvent](0)
        response = EventSourceResponse(
            content=sse_recv,
            data_sender_callable=partial(
                self._pump_channel, channel, reader, sse_send, priming_event, stop_at_response=True
            ),
            headers=self._sse_headers(),
        )
        try:
            await response(scope, receive, send)
        finally:
            # The client is gone (disconnect or delivered response): detach so
            # the handler carries on writing to the store alone.
            channel.detach(reader)
            await sse_send.aclose()
            await sse_recv.aclose()

    async def _pump_channel(
        self,
        channel: _MessageChannel,
        reader: MemoryObjectReceiveStream[EventMessage],
        sse_send: MemoryObjectSendStream[SSEEvent],
        priming_event: SSEEvent | None,
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
        except anyio.ClosedResourceError:  # pragma: lax no cover
            logger.debug("SSE stream closed by close_sse_stream()")
        except Exception:  # pragma: lax no cover
            logger.exception("Error in SSE writer")
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
        sse_send, sse_recv = anyio.create_memory_object_stream[SSEEvent](0)
        response = EventSourceResponse(
            content=sse_recv,
            data_sender_callable=partial(
                self._pump_channel, self._standalone, reader, sse_send, None, stop_at_response=False
            ),
            headers=self._sse_headers(),
        )
        try:
            # This will send headers immediately and establish the SSE connection
            await response(request.scope, request.receive, send)
        except Exception:  # pragma: lax no cover
            logger.exception("Error in standalone SSE response")
        finally:
            self._standalone.detach(reader)
            await sse_send.aclose()
            await sse_recv.aclose()

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
        logger.info(f"Terminating session: {self.mcp_session_id}")

        # Close every open response stream, wake anything awaiting a
        # client answer, and cancel in-flight handlers.
        for channel in list(self._channels.values()):
            channel.close()
        self._channels.clear()
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
            headers = self._sse_headers()

            # The manager only routes supported (or absent) header values to this transport
            replay_protocol_version = request.headers.get(MCP_PROTOCOL_VERSION_HEADER, DEFAULT_NEGOTIATED_VERSION)

            # Create SSE stream for replay
            sse_send, sse_recv = anyio.create_memory_object_stream[SSEEvent](0)

            async def replay_sender() -> None:
                try:
                    async with sse_send:
                        # Define an async callback for sending events
                        async def send_event(event_message: EventMessage) -> None:
                            await sse_send.send(self._create_event_data(event_message))

                        # Replay past events and get the stream ID
                        stream_id = await event_store.replay_events_after(last_event_id, send_event)

                        # Live-tail the stream if it is still open and no response
                        # is currently attached to it: the `close_sse_stream()`
                        # polling reconnect, and a client resuming a dropped connection.
                        if not stream_id:
                            return
                        channel = self._standalone if stream_id == GET_STREAM_KEY else self._channels.get(stream_id)
                        if channel is None or channel.attached:
                            return

                        # Attach first, so anything the still-running request emits
                        # from here on is buffered for this response rather than
                        # only stored. The replay→live-tail ordering window (frames
                        # stored between the replay read and the attach) is pre-existing
                        # and tracked separately.
                        reader = channel.attach()
                        try:
                            # Prime the resumed connection so the client sees the
                            # stream is re-registered.
                            priming_event = await self._mint_priming_event(stream_id, replay_protocol_version)

                            # Forward messages to SSE
                            await self._pump_channel(channel, reader, sse_send, priming_event, stop_at_response=True)
                        finally:
                            channel.detach(reader)
                except anyio.ClosedResourceError:  # pragma: lax no cover
                    # Expected when close_sse_stream() is called
                    logger.debug("Replay SSE stream closed by close_sse_stream()")
                except Exception:  # pragma: lax no cover
                    logger.exception("Error in replay sender")

            # Create and start EventSourceResponse
            response = EventSourceResponse(
                content=sse_recv,
                data_sender_callable=replay_sender,
                headers=headers,
            )

            try:
                await response(request.scope, request.receive, send)
            except Exception:  # pragma: lax no cover
                logger.exception("Error in replay response")
            finally:
                await sse_send.aclose()
                await sse_recv.aclose()

        except Exception:  # pragma: lax no cover
            logger.exception("Error replaying events")
            response = self._create_error_response(
                "Error replaying events",
                HTTPStatus.INTERNAL_SERVER_ERROR,
                INTERNAL_ERROR,
            )
            await response(request.scope, request.receive, send)
