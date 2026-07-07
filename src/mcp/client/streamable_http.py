"""Implements StreamableHTTP transport for MCP clients."""

from __future__ import annotations as _annotations

import contextlib
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import anyio
import httpx
from anyio.abc import TaskGroup
from httpx_sse import EventSource, ServerSentEvent, aconnect_sse
from mcp_types import (
    CONNECTION_CLOSED,
    INTERNAL_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
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
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import ValidationError

from mcp.client._transport import TransportStreams
from mcp.shared._compat import resync_tracer
from mcp.shared._context_streams import ContextReceiveStream, ContextSendStream, create_context_streams
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER
from mcp.shared.jsonrpc_dispatcher import cancelled_request_id_from_params
from mcp.shared.message import ClientMessageMetadata, SessionMessage

logger = logging.getLogger(__name__)


# TODO(Marcelo): Put the TransportStreams in a module under shared, so we can import here.
SessionMessageOrError = SessionMessage | Exception
StreamWriter = ContextSendStream[SessionMessageOrError]
StreamReader = ContextReceiveStream[SessionMessage]

MCP_SESSION_ID = "mcp-session-id"
LAST_EVENT_ID = "last-event-id"

# Reconnection defaults
DEFAULT_RECONNECTION_DELAY_MS = 1000  # 1 second fallback when server doesn't provide retry
MAX_RECONNECTION_ATTEMPTS = 2  # Max retry attempts before giving up


class StreamableHTTPError(Exception):
    """Base exception for StreamableHTTP transport errors."""


class ResumptionError(StreamableHTTPError):
    """Raised when resumption request is invalid."""


@dataclass
class RequestContext:
    """Context for a request operation."""

    client: httpx.AsyncClient
    session_id: str | None
    session_message: SessionMessage
    metadata: ClientMessageMetadata | None
    read_stream_writer: StreamWriter


@dataclass(slots=True)
class _InFlightPost:
    """A request POST in flight: its abort scope and the era it was sent under.

    `modern` is the negotiated-version cache as of this request's dequeue, so a
    later cancel frame is interpreted under the era the request actually ran
    with, not whatever the cache says by then.
    """

    scope: anyio.CancelScope
    modern: bool


class StreamableHTTPTransport:
    """StreamableHTTP client transport implementation."""

    def __init__(self, url: str) -> None:
        """Initialize the StreamableHTTP transport.

        Args:
            url: The endpoint URL.
        """
        self.url = url
        self.session_id: str | None = None
        # Captured from each stamped message's metadata, synchronously in the
        # post_writer loop so the cache always reflects wire order (a POST task's
        # scheduling is arbitrary). Reused on outbound HTTP that carries no
        # per-message header (transport-internal GET/DELETE, and dispatcher-written
        # response/error POSTs that bypass the session's stamp), and consulted by
        # `_consume_modern_cancellation`. Cleared when an `initialize` message is
        # dequeued so a probe-stamped value cannot leak onto the handshake.
        self._protocol_version_header: str | None = None
        # Every request's POST runs inside one of these so an outbound
        # `notifications/cancelled` at 2026 can abort it; see
        # `_consume_modern_cancellation`. Keys are verbatim-typed ("1" is not 1).
        self._in_flight_posts: dict[RequestId, _InFlightPost] = {}

    def _prepare_headers(self) -> dict[str, str]:
        """Build MCP-specific request headers for any outbound HTTP request.

        These are merged with the ``httpx.AsyncClient`` defaults (these take
        precedence). The cached ``MCP-Protocol-Version`` is included whenever
        present so messages that don't pass through the session's stamp —
        response/error POSTs, legacy cancel frames, transport-internal
        GET/DELETE — still carry the negotiated version. Per-message headers
        are layered on top by the caller.
        """
        headers: dict[str, str] = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }
        if self.session_id:
            headers[MCP_SESSION_ID] = self.session_id
        if self._protocol_version_header:
            headers[MCP_PROTOCOL_VERSION_HEADER] = self._protocol_version_header
        return headers

    def _is_initialization_request(self, message: JSONRPCMessage) -> bool:
        """Check if the message is an initialization request."""
        return isinstance(message, JSONRPCRequest) and message.method == "initialize"

    def _is_initialized_notification(self, message: JSONRPCMessage) -> bool:
        """Check if the message is an initialized notification."""
        return isinstance(message, JSONRPCNotification) and message.method == "notifications/initialized"

    def _maybe_extract_session_id_from_response(self, response: httpx.Response) -> None:
        """Extract and store session ID from response headers."""
        new_session_id = response.headers.get(MCP_SESSION_ID)
        if new_session_id:
            self.session_id = new_session_id
            logger.info(f"Received session ID: {self.session_id}")

    async def _handle_sse_event(
        self,
        sse: ServerSentEvent,
        read_stream_writer: StreamWriter,
        original_request_id: RequestId | None = None,
        resumption_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> bool:
        """Handle an SSE event, returning True if the response is complete."""
        if sse.event == "message":
            # Handle priming events (empty data with ID) for resumability
            if not sse.data:
                # Call resumption callback for priming events that have an ID
                if sse.id and resumption_callback:
                    await resumption_callback(sse.id)
                return False
            try:
                message = jsonrpc_message_adapter.validate_json(sse.data, by_name=False)
                logger.debug(f"SSE message: {message}")

                # If this is a response and we have original_request_id, replace it
                if original_request_id is not None and isinstance(message, JSONRPCResponse | JSONRPCError):
                    message.id = original_request_id

                session_message = SessionMessage(message)
                await read_stream_writer.send(session_message)

                # Call resumption token callback if we have an ID
                if sse.id and resumption_callback:
                    await resumption_callback(sse.id)

                # If this is a response or error return True indicating completion
                # Otherwise, return False to continue listening
                return isinstance(message, JSONRPCResponse | JSONRPCError)

            # Forwarding to a closed read stream lands here when the caller cancels mid-SSE
            # (BrokenResourceError, not a parse failure); coverage is timing-dependent in the
            # streaming story's modern HTTP cancellation leg.
            except Exception as exc:  # pragma: lax no cover
                logger.exception("Error parsing SSE message")
                if original_request_id is not None:
                    error_data = ErrorData(code=PARSE_ERROR, message=f"Failed to parse SSE message: {exc}")
                    error_msg = SessionMessage(JSONRPCError(jsonrpc="2.0", id=original_request_id, error=error_data))
                    await read_stream_writer.send(error_msg)
                    return True
                await read_stream_writer.send(exc)
                return False
        else:  # pragma: no cover
            logger.warning(f"Unknown SSE event: {sse.event}")
            return False

    async def handle_get_stream(self, client: httpx.AsyncClient, read_stream_writer: StreamWriter) -> None:
        """Handle GET stream for server-initiated messages with auto-reconnect."""
        last_event_id: str | None = None
        retry_interval_ms: int | None = None
        attempt: int = 0

        while attempt < MAX_RECONNECTION_ATTEMPTS:  # pragma: no branch
            try:
                if not self.session_id:
                    return

                headers = self._prepare_headers()
                if last_event_id:
                    headers[LAST_EVENT_ID] = last_event_id

                async with aconnect_sse(client, "GET", self.url, headers=headers) as event_source:
                    event_source.response.raise_for_status()
                    logger.debug("GET SSE connection established")

                    async for sse in event_source.aiter_sse():
                        # Track last event ID for reconnection
                        if sse.id:
                            last_event_id = sse.id
                        # Track retry interval from server
                        if sse.retry is not None:
                            retry_interval_ms = sse.retry

                        await self._handle_sse_event(sse, read_stream_writer)

                    # Stream ended normally (server closed) - reset attempt counter
                    attempt = 0

            except Exception:
                logger.debug("GET stream error", exc_info=True)
                attempt += 1

            if attempt >= MAX_RECONNECTION_ATTEMPTS:  # pragma: no cover
                logger.debug(f"GET stream max reconnection attempts ({MAX_RECONNECTION_ATTEMPTS}) exceeded")
                return

            # Wait before reconnecting
            delay_ms = retry_interval_ms if retry_interval_ms is not None else DEFAULT_RECONNECTION_DELAY_MS
            logger.info(f"GET stream disconnected, reconnecting in {delay_ms}ms...")
            await anyio.sleep(delay_ms / 1000.0)

    async def _handle_resumption_request(self, ctx: RequestContext) -> None:
        """Handle a resumption request using GET with SSE."""
        headers = self._prepare_headers()
        if ctx.metadata and ctx.metadata.resumption_token:
            headers[LAST_EVENT_ID] = ctx.metadata.resumption_token
        else:
            raise ResumptionError("Resumption request requires a resumption token")  # pragma: no cover

        # Extract original request ID to map responses
        original_request_id = None
        if isinstance(ctx.session_message.message, JSONRPCRequest):  # pragma: no branch
            original_request_id = ctx.session_message.message.id

        async with aconnect_sse(ctx.client, "GET", self.url, headers=headers) as event_source:
            event_source.response.raise_for_status()
            logger.debug("Resumption GET SSE connection established")

            async for sse in event_source.aiter_sse():  # pragma: no branch
                is_complete = await self._handle_sse_event(
                    sse,
                    ctx.read_stream_writer,
                    original_request_id,
                    ctx.metadata.on_resumption_token_update if ctx.metadata else None,
                )
                if is_complete:
                    await event_source.response.aclose()
                    break

    def _consume_modern_cancellation(self, session_message: SessionMessage) -> bool:
        """Translate an outbound `notifications/cancelled` at 2026; True means "do not POST".

        The 2026 wire defines no client-to-server notifications over streamable
        HTTP: closing a request's response stream IS its cancellation signal.
        The dispatcher still emits the courtesy frame as its abandon signal
        (every outbound cancel names one of our own request ids - the spec
        forbids cancelling a request the sender did not issue), so this
        transport translates it: when the named request's POST is in flight,
        that POST's own recorded era decides - abort-and-swallow at 2026, POST
        the frame below it (where the frame is the signal and a disconnect
        explicitly is not). With no POST to consult, the cached negotiated
        version decides; at 2026 the frame is swallowed even unmatched, so a
        late cancel racing the response cannot leak onto the wire.
        """
        message = session_message.message
        if not (isinstance(message, JSONRPCNotification) and message.method == "notifications/cancelled"):
            return False
        request_id = cancelled_request_id_from_params(message.params)
        post = self._in_flight_posts.get(request_id) if request_id is not None else None
        if post is not None:
            if not post.modern:
                return False
            logger.debug("aborting in-flight POST for cancelled request %r", request_id)
            post.scope.cancel()
            return True
        return self._protocol_version_header in MODERN_PROTOCOL_VERSIONS

    async def _run_request_post(
        self,
        post_fn: Callable[[], Awaitable[None]],
        post: _InFlightPost,
        request_id: RequestId,
    ) -> None:
        """Run one request's POST inside its abort scope (see `_consume_modern_cancellation`)."""
        try:
            with post.scope:
                await post_fn()
        finally:
            # Identity-guarded: a reused id may already have a successor
            # registered while this task unwinds - popping by key alone would
            # evict the live entry and leave the new POST unabortable.
            if self._in_flight_posts.get(request_id) is post:
                del self._in_flight_posts[request_id]

    async def _handle_post_request(self, ctx: RequestContext) -> None:
        """Handle a POST request with response processing."""
        message = ctx.session_message.message
        headers = self._prepare_headers()
        if ctx.metadata is not None and ctx.metadata.headers is not None:
            headers.update(ctx.metadata.headers)

        async with ctx.client.stream(
            "POST",
            self.url,
            json=message.model_dump(by_alias=True, mode="json", exclude_unset=True),
            headers=headers,
        ) as response:
            if response.status_code == 202:
                logger.debug("Received 202 Accepted")
                if isinstance(message, JSONRPCRequest):
                    # A request's response arrives on this POST's body; 202 says
                    # none will follow. Resolve rather than park the caller forever.
                    await self._resolve_abandoned_request(
                        ctx.read_stream_writer,
                        message.id,
                        "server answered a request with 202 Accepted",
                        code=INVALID_REQUEST,
                    )
                return

            if response.status_code >= 400:
                if isinstance(message, JSONRPCRequest):
                    # A spec-correct server may return the JSON-RPC error in the
                    # body at a non-2xx status (e.g. 400 for INVALID_PARAMS, 404
                    # for METHOD_NOT_FOUND). Surface that error rather than the
                    # status-derived stand-in below.
                    if response.headers.get("content-type", "").lower().startswith("application/json"):
                        try:
                            body = await response.aread()
                            parsed = jsonrpc_message_adapter.validate_json(body, by_name=False)
                            if isinstance(parsed, JSONRPCError):
                                # The server may have set `id: null` (request rejected before its
                                # id was parsed); use this request's id so correlation works.
                                reply = JSONRPCError(jsonrpc="2.0", id=message.id, error=parsed.error)
                                await ctx.read_stream_writer.send(SessionMessage(reply))
                                return
                        except (httpx.StreamError, ValidationError):
                            pass
                        logger.debug("Non-2xx body was not a JSON-RPC error; using fallback")
                    if response.status_code == 404:
                        if self.session_id is None:
                            # No session yet → 404 is the HTTP-level spelling of
                            # METHOD_NOT_FOUND (gateway / legacy server doesn't know
                            # this method); "Session terminated" would be a lie here.
                            error_data = ErrorData(code=METHOD_NOT_FOUND, message="Not Found")
                        else:
                            error_data = ErrorData(code=INVALID_REQUEST, message="Session terminated")
                    else:
                        error_data = ErrorData(code=INTERNAL_ERROR, message="Server returned an error response")
                    session_message = SessionMessage(JSONRPCError(jsonrpc="2.0", id=message.id, error=error_data))
                    await ctx.read_stream_writer.send(session_message)
                return

            if self._is_initialization_request(message):
                self._maybe_extract_session_id_from_response(response)

            # Per https://modelcontextprotocol.io/specification/2025-06-18/basic#notifications:
            # The server MUST NOT send a response to notifications.
            if isinstance(message, JSONRPCRequest):
                content_type = response.headers.get("content-type", "").lower()
                if content_type.startswith("application/json"):
                    await self._handle_json_response(response, ctx.read_stream_writer, request_id=message.id)
                elif content_type.startswith("text/event-stream"):
                    await self._handle_sse_response(response, ctx)
                else:
                    logger.error(f"Unexpected content type: {content_type}")
                    error_data = ErrorData(code=INVALID_REQUEST, message=f"Unexpected content type: {content_type}")
                    error_msg = SessionMessage(JSONRPCError(jsonrpc="2.0", id=message.id, error=error_data))
                    await ctx.read_stream_writer.send(error_msg)

    async def _handle_json_response(
        self,
        response: httpx.Response,
        read_stream_writer: StreamWriter,
        *,
        request_id: RequestId,
    ) -> None:
        """Handle JSON response from the server."""
        try:
            content = await response.aread()
            message = jsonrpc_message_adapter.validate_json(content, by_name=False)
            session_message = SessionMessage(message)
            await read_stream_writer.send(session_message)
        except (httpx.StreamError, ValidationError) as exc:
            logger.exception("Error parsing JSON response")
            error_data = ErrorData(code=PARSE_ERROR, message=f"Failed to parse JSON response: {exc}")
            error_msg = SessionMessage(JSONRPCError(jsonrpc="2.0", id=request_id, error=error_data))
            await read_stream_writer.send(error_msg)

    async def _handle_sse_response(
        self,
        response: httpx.Response,
        ctx: RequestContext,
    ) -> None:
        """Handle SSE response from the server."""
        last_event_id: str | None = None
        retry_interval_ms: int | None = None

        # The caller (_handle_post_request) only reaches here inside
        # isinstance(message, JSONRPCRequest), so this is always a JSONRPCRequest.
        assert isinstance(ctx.session_message.message, JSONRPCRequest)
        original_request_id = ctx.session_message.message.id

        try:
            event_source = EventSource(response)
            async for sse in event_source.aiter_sse():  # pragma: no branch
                # Track last event ID for potential reconnection
                if sse.id:
                    last_event_id = sse.id

                # Track retry interval from server
                if sse.retry is not None:
                    retry_interval_ms = sse.retry

                is_complete = await self._handle_sse_event(
                    sse,
                    ctx.read_stream_writer,
                    original_request_id=original_request_id,
                    resumption_callback=(ctx.metadata.on_resumption_token_update if ctx.metadata else None),
                )
                # If the SSE event indicates completion, like returning response/error
                # break the loop
                if is_complete:
                    await response.aclose()
                    return  # Normal completion, no reconnect needed
        except Exception:
            logger.debug("SSE stream ended", exc_info=True)  # pragma: lax no cover

        # Stream ended without response - reconnect if we received an event with ID
        if last_event_id is not None:
            logger.info("SSE stream disconnected, reconnecting...")
            await self._handle_reconnection(ctx, last_event_id, retry_interval_ms)
        else:
            # Not resumable: resolve the waiter, else a listen stream's consumer
            # would hang forever instead of learning the subscription is lost.
            await self._resolve_abandoned_request(
                ctx.read_stream_writer, original_request_id, "SSE stream ended without a response"
            )

    async def _resolve_abandoned_request(
        self, read_stream_writer: StreamWriter, request_id: RequestId, message: str, *, code: int = CONNECTION_CLOSED
    ) -> None:
        """Resolve a request whose response can never arrive with a synthesized error.

        Best-effort: a closed read stream means the session is tearing down.
        """
        error_data = ErrorData(code=code, message=message)
        error_msg = SessionMessage(JSONRPCError(jsonrpc="2.0", id=request_id, error=error_data))
        try:
            await read_stream_writer.send(error_msg)
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            logger.debug("read stream closed before request %r could be resolved", request_id)

    async def _handle_reconnection(
        self,
        ctx: RequestContext,
        last_event_id: str,
        retry_interval_ms: int | None = None,
        attempt: int = 0,
    ) -> None:
        """Reconnect with Last-Event-ID to resume stream after server disconnect."""
        # Only requests reconnect: every caller arrives from a request's response stream.
        assert isinstance(ctx.session_message.message, JSONRPCRequest)
        original_request_id = ctx.session_message.message.id

        if attempt >= MAX_RECONNECTION_ATTEMPTS:
            # Resolve on give-up: a request with no read timeout (a listen
            # stream) would otherwise hang its caller forever.
            logger.debug(f"Max reconnection attempts ({MAX_RECONNECTION_ATTEMPTS}) exceeded")
            await self._resolve_abandoned_request(
                ctx.read_stream_writer, original_request_id, "SSE stream ended and reconnection attempts were exhausted"
            )
            return

        # Always wait - use server value or default
        delay_ms = retry_interval_ms if retry_interval_ms is not None else DEFAULT_RECONNECTION_DELAY_MS
        await anyio.sleep(delay_ms / 1000.0)

        headers = self._prepare_headers()
        headers[LAST_EVENT_ID] = last_event_id

        try:
            async with aconnect_sse(ctx.client, "GET", self.url, headers=headers) as event_source:
                event_source.response.raise_for_status()
                logger.info("Reconnected to SSE stream")

                # Track for potential further reconnection
                reconnect_last_event_id: str = last_event_id
                reconnect_retry_ms = retry_interval_ms

                async for sse in event_source.aiter_sse():
                    if sse.id:  # pragma: no branch
                        reconnect_last_event_id = sse.id
                    if sse.retry is not None:
                        reconnect_retry_ms = sse.retry

                    is_complete = await self._handle_sse_event(
                        sse,
                        ctx.read_stream_writer,
                        original_request_id,
                        ctx.metadata.on_resumption_token_update if ctx.metadata else None,
                    )
                    if is_complete:
                        await event_source.response.aclose()
                        return

                # Stream ended again without response - reconnect again (reset attempt counter)
                logger.info("SSE stream disconnected, reconnecting...")
                await self._handle_reconnection(ctx, reconnect_last_event_id, reconnect_retry_ms, 0)
        except Exception as e:  # pragma: no cover
            logger.debug(f"Reconnection failed: {e}")
            # Try to reconnect again if we still have an event ID
            await self._handle_reconnection(ctx, last_event_id, retry_interval_ms, attempt + 1)

    async def post_writer(
        self,
        client: httpx.AsyncClient,
        write_stream_reader: StreamReader,
        read_stream_writer: StreamWriter,
        write_stream: ContextSendStream[SessionMessage],
        start_get_stream: Callable[[], None],
        tg: TaskGroup,
    ) -> None:
        """Handle writing requests to the server."""
        try:
            async with write_stream_reader, read_stream_writer, write_stream:

                async def _handle_message(session_message: SessionMessage) -> None:
                    message = session_message.message
                    if self._consume_modern_cancellation(session_message):
                        return
                    metadata = (
                        session_message.metadata
                        if isinstance(session_message.metadata, ClientMessageMetadata)
                        else None
                    )

                    # Check if this is a resumption request
                    is_resumption = bool(metadata and metadata.resumption_token)

                    logger.debug(f"Sending client message: {message}")

                    # Handle initialized notification
                    if self._is_initialized_notification(message):
                        start_get_stream()

                    if self._is_initialization_request(message):
                        # `initialize` is the negotiation, not a "subsequent request" — discard any
                        # probe-stamped value so the discover→fallback path can't leak it onto the handshake.
                        self._protocol_version_header = None
                    elif metadata is not None and metadata.headers is not None:
                        stamped_version = metadata.headers.get(MCP_PROTOCOL_VERSION_HEADER)
                        if stamped_version is not None:
                            self._protocol_version_header = stamped_version

                    ctx = RequestContext(
                        client=client,
                        session_id=self.session_id,
                        session_message=session_message,
                        metadata=metadata,
                        read_stream_writer=read_stream_writer,
                    )

                    async def handle_request_async():
                        if is_resumption:
                            await self._handle_resumption_request(ctx)
                        else:
                            await self._handle_post_request(ctx)

                    # If this is a request, start a new task to handle it
                    if isinstance(message, JSONRPCRequest):
                        # Register the abort scope before the spawn: the next
                        # message through this loop can already be the abandon
                        # signal for this id, ahead of the task ever running.
                        post = _InFlightPost(
                            scope=anyio.CancelScope(),
                            modern=self._protocol_version_header in MODERN_PROTOCOL_VERSIONS,
                        )
                        superseded = self._in_flight_posts.get(message.id)
                        if superseded is not None:
                            # A reused id means the waiter belongs to this attempt now:
                            # sever the old POST so its zombie stream cannot answer,
                            # fail, or resolve the successor's request.
                            superseded.scope.cancel()
                        self._in_flight_posts[message.id] = post
                        tg.start_soon(self._run_request_post, handle_request_async, post, message.id)
                    else:
                        await handle_request_async()

                async for session_message in write_stream_reader:
                    sender_ctx = write_stream_reader.last_context
                    if sender_ctx is not None:
                        async with anyio.create_task_group() as tg_local:
                            sender_ctx.run(tg_local.start_soon, _handle_message, session_message)
                    else:
                        await _handle_message(session_message)  # pragma: no cover

        except Exception:  # pragma: lax no cover
            logger.exception("Error in post_writer")

    async def terminate_session(self, client: httpx.AsyncClient) -> None:
        """Terminate the session by sending a DELETE request."""
        if not self.session_id:
            return  # pragma: no cover

        try:
            headers = self._prepare_headers()
            response = await client.delete(self.url, headers=headers)

            if response.status_code == 405:
                logger.debug("Server does not allow session termination")
            elif response.status_code not in (200, 204):
                logger.warning(f"Session termination failed: {response.status_code}")  # pragma: no cover
        except Exception as exc:  # pragma: no cover
            logger.warning(f"Session termination failed: {exc}")

    # TODO(Marcelo): Check the TODO below, and cover this with tests if necessary.
    def get_session_id(self) -> str | None:
        """Get the current session ID."""
        return self.session_id  # pragma: no cover


# TODO(Marcelo): I've dropped the `get_session_id` callback because it breaks the Transport protocol. Is that needed?
# It's a completely wrong abstraction, so removal is a good idea. But if we need the client to find the session ID,
# we should think about a better way to do it. I believe we can achieve it with other means.
@asynccontextmanager
async def streamable_http_client(
    url: str,
    *,
    http_client: httpx.AsyncClient | None = None,
    terminate_on_close: bool = True,
) -> AsyncGenerator[TransportStreams, None]:
    """Client transport for StreamableHTTP.

    Args:
        url: The MCP server endpoint URL.
        http_client: Optional pre-configured httpx.AsyncClient. If None, a default
            client with recommended MCP timeouts will be created. To configure headers,
            authentication, or other HTTP settings, create an httpx.AsyncClient and pass it here.
        terminate_on_close: If True, send a DELETE request to terminate the session when the context exits.

    Yields:
        Tuple containing:
            - read_stream: Stream for reading messages from the server
            - write_stream: Stream for sending messages to the server

    Example:
        See examples/snippets/clients/ for usage patterns.
    """
    # Determine if we need to create and manage the client
    client_provided = http_client is not None
    client = http_client

    if client is None:
        # Create default client with recommended MCP timeouts
        client = create_mcp_http_client()

    transport = StreamableHTTPTransport(url)

    logger.debug(f"Connecting to StreamableHTTP endpoint: {url}")

    async with contextlib.AsyncExitStack() as stack:
        # Only manage client lifecycle if we created it
        if not client_provided:
            await stack.enter_async_context(client)

        read_stream_writer, read_stream = create_context_streams[SessionMessage | Exception](0)
        write_stream, write_stream_reader = create_context_streams[SessionMessage](0)

        async with (
            read_stream_writer,
            read_stream,
            write_stream,
            write_stream_reader,
            anyio.create_task_group() as tg,
        ):

            def start_get_stream() -> None:
                tg.start_soon(transport.handle_get_stream, client, read_stream_writer)

            tg.start_soon(
                transport.post_writer,
                client,
                write_stream_reader,
                read_stream_writer,
                write_stream,
                start_get_stream,
                tg,
            )

            try:
                yield read_stream, write_stream
            finally:
                if transport.session_id and terminate_on_close:
                    await transport.terminate_session(client)
                tg.cancel_scope.cancel()
        await resync_tracer()
