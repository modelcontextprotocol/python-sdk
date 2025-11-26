"""
StreamableHTTP Client Transport Module

This module implements the StreamableHTTP transport for MCP clients,
providing support for HTTP POST requests with optional SSE streaming responses
and session management.
"""

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

import anyio
import httpx
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from httpx_sse import EventSource, ServerSentEvent, aconnect_sse

from mcp.shared._httpx_utils import McpHttpClientFactory, create_mcp_http_client
from mcp.shared.message import ClientMessageMetadata, SessionMessage
from mcp.types import (
    ErrorData,
    InitializeResult,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    RequestId,
)

logger = logging.getLogger(__name__)


SessionMessageOrError = SessionMessage | Exception
StreamWriter = MemoryObjectSendStream[SessionMessageOrError]
StreamReader = MemoryObjectReceiveStream[SessionMessage]
GetSessionIdCallback = Callable[[], str | None]

MCP_SESSION_ID = "mcp-session-id"
MCP_PROTOCOL_VERSION = "mcp-protocol-version"
LAST_EVENT_ID = "last-event-id"
CONTENT_TYPE = "content-type"
ACCEPT = "accept"


JSON = "application/json"
SSE = "text/event-stream"


class StreamableHTTPError(Exception):
    """Base exception for StreamableHTTP transport errors."""


class ResumptionError(StreamableHTTPError):
    """Raised when resumption request is invalid."""


@dataclass
class StreamableHTTPReconnectionOptions:
    """Configuration options for reconnection behavior of StreamableHTTPTransport.

    Attributes:
        initial_reconnection_delay: Initial backoff time in seconds. Default is 1.0.
        max_reconnection_delay: Maximum backoff time in seconds. Default is 30.0.
        reconnection_delay_grow_factor: Factor by which delay increases. Default is 1.5.
        max_retries: Maximum reconnection attempts. Default is 2.
    """

    initial_reconnection_delay: float = 1.0
    max_reconnection_delay: float = 30.0
    reconnection_delay_grow_factor: float = 1.5
    max_retries: int = 2

    def __post_init__(self) -> None:
        if self.initial_reconnection_delay > self.max_reconnection_delay:
            raise ValueError("initial_reconnection_delay cannot exceed max_reconnection_delay")


@dataclass
class RequestContext:
    """Context for a request operation."""

    client: httpx.AsyncClient
    headers: dict[str, str]
    session_id: str | None
    session_message: SessionMessage
    metadata: ClientMessageMetadata | None
    read_stream_writer: StreamWriter
    sse_read_timeout: float


class StreamableHTTPTransport:
    """StreamableHTTP client transport implementation."""

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float | timedelta = 30,
        sse_read_timeout: float | timedelta = 60 * 5,
        auth: httpx.Auth | None = None,
        reconnection_options: StreamableHTTPReconnectionOptions | None = None,
    ) -> None:
        """Initialize the StreamableHTTP transport."""
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout.total_seconds() if isinstance(timeout, timedelta) else timeout
        self.sse_read_timeout = (
            sse_read_timeout.total_seconds() if isinstance(sse_read_timeout, timedelta) else sse_read_timeout
        )
        self.auth = auth
        self.session_id = None
        self.protocol_version = None
        self.reconnection_options = reconnection_options or StreamableHTTPReconnectionOptions()
        self._server_retry_seconds: float | None = None  # Server-provided retry delay
        self.request_headers = {
            ACCEPT: f"{JSON}, {SSE}",
            CONTENT_TYPE: JSON,
            **self.headers,
        }

    def _prepare_request_headers(self, base_headers: dict[str, str]) -> dict[str, str]:
        """Update headers with session ID and protocol version if available."""
        headers = base_headers.copy()
        if self.session_id:
            headers[MCP_SESSION_ID] = self.session_id
        if self.protocol_version:
            headers[MCP_PROTOCOL_VERSION] = self.protocol_version
        return headers

    def _is_initialization_request(self, message: JSONRPCMessage) -> bool:
        """Check if the message is an initialization request."""
        return isinstance(message.root, JSONRPCRequest) and message.root.method == "initialize"

    def _is_initialized_notification(self, message: JSONRPCMessage) -> bool:
        """Check if the message is an initialized notification."""
        return isinstance(message.root, JSONRPCNotification) and message.root.method == "notifications/initialized"

    def _maybe_extract_session_id_from_response(
        self,
        response: httpx.Response,
    ) -> None:
        """Extract and store session ID from response headers."""
        new_session_id = response.headers.get(MCP_SESSION_ID)
        if new_session_id:
            self.session_id = new_session_id
            logger.info(f"Received session ID: {self.session_id}")

    def _maybe_extract_protocol_version_from_message(
        self,
        message: JSONRPCMessage,
    ) -> None:
        """Extract protocol version from initialization response message."""
        if isinstance(message.root, JSONRPCResponse) and message.root.result:  # pragma: no branch
            try:
                # Parse the result as InitializeResult for type safety
                init_result = InitializeResult.model_validate(message.root.result)
                self.protocol_version = str(init_result.protocolVersion)
                logger.info(f"Negotiated protocol version: {self.protocol_version}")
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    f"Failed to parse initialization response as InitializeResult: {exc}"
                )  # pragma: no cover
                logger.warning(f"Raw result: {message.root.result}")

    def _get_next_reconnection_delay(self, attempt: int) -> float:
        """Calculate the next reconnection delay using exponential backoff.

        Args:
            attempt: Current reconnection attempt count

        Returns:
            Time to wait in seconds before next reconnection attempt
        """
        # Use server-provided retry value if available
        if self._server_retry_seconds is not None:
            return self._server_retry_seconds

        # Fall back to exponential backoff
        opts = self.reconnection_options
        delay = opts.initial_reconnection_delay * (opts.reconnection_delay_grow_factor**attempt)
        return min(delay, opts.max_reconnection_delay)

    async def _handle_sse_event(
        self,
        sse: ServerSentEvent,
        read_stream_writer: StreamWriter,
        original_request_id: RequestId | None = None,
        resumption_callback: Callable[[str], Awaitable[None]] | None = None,
        is_initialization: bool = False,
    ) -> tuple[bool, bool]:
        """Handle an SSE event.

        Returns:
            Tuple of (is_complete, has_event_id) where:
            - is_complete: True if the response stream is complete (got response/error)
            - has_event_id: True if this event had an ID (indicating resumability)
        """
        event_id = sse.id  # httpx_sse defaults to "" for missing ID
        has_event_id = bool(event_id)  # True if non-empty string

        # Capture server-provided retry value for reconnection timing
        if sse.retry is not None:  # pragma: no cover
            self._server_retry_seconds = sse.retry / 1000.0  # Convert ms to seconds

        if sse.event == "message":
            # Check for priming event (empty data but may have ID for resumption)
            if not sse.data or not sse.data.strip():
                # Priming event - just track the ID for resumption
                if has_event_id and resumption_callback:
                    await resumption_callback(event_id)
                return False, has_event_id

            try:
                message = JSONRPCMessage.model_validate_json(sse.data)
                logger.debug(f"SSE message: {message}")

                # Extract protocol version from initialization response
                if is_initialization:
                    self._maybe_extract_protocol_version_from_message(message)

                # If this is a response and we have original_request_id, replace it
                if original_request_id is not None and isinstance(message.root, JSONRPCResponse | JSONRPCError):
                    message.root.id = original_request_id

                session_message = SessionMessage(message)
                await read_stream_writer.send(session_message)

                # Call resumption token callback if we have an ID
                if has_event_id and resumption_callback:
                    await resumption_callback(event_id)

                # If this is a response or error return True indicating completion
                # Otherwise, return False to continue listening
                return isinstance(message.root, JSONRPCResponse | JSONRPCError), has_event_id

            except Exception as exc:  # pragma: no cover
                logger.exception("Error parsing SSE message")
                await read_stream_writer.send(exc)
                return False, has_event_id
        else:  # pragma: no cover
            # Empty event or priming event - not a completion, but may have ID
            # httpx_sse defaults event to "message", so this handles non-standard events
            if has_event_id and resumption_callback:
                # Priming event - call resumption callback
                await resumption_callback(event_id)
            return False, has_event_id

    async def handle_get_stream(
        self,
        client: httpx.AsyncClient,
        read_stream_writer: StreamWriter,
    ) -> None:
        """Handle GET stream for server-initiated messages."""
        try:
            if not self.session_id:
                return

            headers = self._prepare_request_headers(self.request_headers)

            async with aconnect_sse(
                client,
                "GET",
                self.url,
                headers=headers,
                timeout=httpx.Timeout(self.timeout, read=self.sse_read_timeout),
            ) as event_source:
                event_source.response.raise_for_status()
                logger.debug("GET SSE connection established")

                async for sse in event_source.aiter_sse():
                    _is_complete, _has_event_id = await self._handle_sse_event(sse, read_stream_writer)

        except Exception as exc:
            logger.debug(f"GET stream error (non-fatal): {exc}")  # pragma: no cover

    async def _handle_resumption_request(self, ctx: RequestContext) -> None:
        """Handle a resumption request using GET with SSE."""
        headers = self._prepare_request_headers(ctx.headers)
        if ctx.metadata and ctx.metadata.resumption_token:
            headers[LAST_EVENT_ID] = ctx.metadata.resumption_token
        else:
            raise ResumptionError("Resumption request requires a resumption token")  # pragma: no cover

        # Extract original request ID to map responses
        original_request_id = None
        if isinstance(ctx.session_message.message.root, JSONRPCRequest):  # pragma: no branch
            original_request_id = ctx.session_message.message.root.id

        async with aconnect_sse(
            ctx.client,
            "GET",
            self.url,
            headers=headers,
            timeout=httpx.Timeout(self.timeout, read=self.sse_read_timeout),
        ) as event_source:
            event_source.response.raise_for_status()
            logger.debug("Resumption GET SSE connection established")

            async for sse in event_source.aiter_sse():  # pragma: no branch
                is_complete, _has_event_id = await self._handle_sse_event(
                    sse,
                    ctx.read_stream_writer,
                    original_request_id,
                    ctx.metadata.on_resumption_token_update if ctx.metadata else None,
                )
                if is_complete:
                    await event_source.response.aclose()
                    break

    async def _handle_post_request(self, ctx: RequestContext) -> None:
        """Handle a POST request with response processing."""
        headers = self._prepare_request_headers(ctx.headers)
        message = ctx.session_message.message
        is_initialization = self._is_initialization_request(message)

        async with ctx.client.stream(
            "POST",
            self.url,
            json=message.model_dump(by_alias=True, mode="json", exclude_none=True),
            headers=headers,
        ) as response:
            if response.status_code == 202:
                logger.debug("Received 202 Accepted")
                return

            if response.status_code == 404:  # pragma: no branch
                if isinstance(message.root, JSONRPCRequest):
                    await self._send_session_terminated_error(  # pragma: no cover
                        ctx.read_stream_writer,  # pragma: no cover
                        message.root.id,  # pragma: no cover
                    )  # pragma: no cover
                return  # pragma: no cover

            response.raise_for_status()
            if is_initialization:
                self._maybe_extract_session_id_from_response(response)

            # Per https://modelcontextprotocol.io/specification/2025-06-18/basic#notifications:
            # The server MUST NOT send a response to notifications.
            if isinstance(message.root, JSONRPCRequest):
                content_type = response.headers.get(CONTENT_TYPE, "").lower()
                if content_type.startswith(JSON):
                    await self._handle_json_response(response, ctx.read_stream_writer, is_initialization)
                elif content_type.startswith(SSE):
                    await self._handle_sse_response(response, ctx, is_initialization)
                else:
                    await self._handle_unexpected_content_type(  # pragma: no cover
                        content_type,  # pragma: no cover
                        ctx.read_stream_writer,  # pragma: no cover
                    )  # pragma: no cover

    async def _handle_json_response(
        self,
        response: httpx.Response,
        read_stream_writer: StreamWriter,
        is_initialization: bool = False,
    ) -> None:
        """Handle JSON response from the server."""
        try:
            content = await response.aread()
            message = JSONRPCMessage.model_validate_json(content)

            # Extract protocol version from initialization response
            if is_initialization:
                self._maybe_extract_protocol_version_from_message(message)

            session_message = SessionMessage(message)
            await read_stream_writer.send(session_message)
        except Exception as exc:  # pragma: no cover
            logger.exception("Error parsing JSON response")
            await read_stream_writer.send(exc)

    async def _handle_sse_response(
        self,
        response: httpx.Response,
        ctx: RequestContext,
        is_initialization: bool = False,
        attempt: int = 0,
    ) -> tuple[bool, str | None]:
        """Handle SSE response from the server with automatic reconnection.

        Returns:
            Tuple of (has_priming_event, last_event_id) where:
            - has_priming_event: True if any event had an ID (priming event received)
            - last_event_id: The last event ID received, for resumption
        """
        has_priming_event = False
        last_event_id: str | None = None
        is_complete = False

        try:
            event_source = EventSource(response)
            async for sse in event_source.aiter_sse():  # pragma: no branch
                is_complete, has_event_id = await self._handle_sse_event(
                    sse,
                    ctx.read_stream_writer,
                    resumption_callback=(ctx.metadata.on_resumption_token_update if ctx.metadata else None),
                    is_initialization=is_initialization,
                )

                # Track priming events
                if has_event_id:
                    has_priming_event = True
                    last_event_id = sse.id

                # If the SSE event indicates completion, like returning response/error
                # break the loop
                if is_complete:
                    await response.aclose()
                    break
        except Exception as e:  # pragma: no cover
            logger.exception("Error reading SSE stream:")
            # Don't send exception if we can reconnect
            if not (has_priming_event and last_event_id):
                await ctx.read_stream_writer.send(e)

        # Auto-reconnect if stream ended without completion and we have priming event
        if not is_complete and has_priming_event and last_event_id:  # pragma: no cover
            await self._attempt_sse_reconnection(ctx, last_event_id, attempt)

        return has_priming_event, last_event_id

    async def _attempt_sse_reconnection(  # pragma: no cover
        self,
        ctx: RequestContext,
        last_event_id: str,
        attempt: int,
    ) -> None:
        """Attempt to reconnect to SSE stream using resumption token.

        Called when SSE stream ends without receiving a response/error,
        but we have a priming event indicating resumability.
        """
        max_retries = self.reconnection_options.max_retries

        if attempt >= max_retries:
            error_msg = f"Max reconnection attempts ({max_retries}) exceeded"
            logger.error(error_msg)
            await ctx.read_stream_writer.send(StreamableHTTPError(error_msg))
            return

        # Calculate delay (uses server retry if available, else exponential backoff)
        delay = self._get_next_reconnection_delay(attempt)
        logger.info(f"SSE stream closed, reconnecting in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")

        await anyio.sleep(delay)

        # Build resumption context with last_event_id
        resumption_metadata = ClientMessageMetadata(
            resumption_token=last_event_id,
            on_resumption_token_update=(ctx.metadata.on_resumption_token_update if ctx.metadata else None),
        )

        resumption_ctx = RequestContext(
            client=ctx.client,
            headers=ctx.headers,
            session_id=ctx.session_id,
            session_message=ctx.session_message,
            metadata=resumption_metadata,
            read_stream_writer=ctx.read_stream_writer,
            sse_read_timeout=ctx.sse_read_timeout,
        )

        try:
            await self._handle_resumption_request(resumption_ctx)
        except Exception as e:
            logger.warning(f"Reconnection attempt {attempt + 1} failed: {e}")
            # Recursive retry with incremented attempt counter
            await self._attempt_sse_reconnection(ctx, last_event_id, attempt + 1)

    async def _handle_unexpected_content_type(
        self,
        content_type: str,
        read_stream_writer: StreamWriter,
    ) -> None:  # pragma: no cover
        """Handle unexpected content type in response."""
        error_msg = f"Unexpected content type: {content_type}"  # pragma: no cover
        logger.error(error_msg)  # pragma: no cover
        await read_stream_writer.send(ValueError(error_msg))  # pragma: no cover

    async def _send_session_terminated_error(
        self,
        read_stream_writer: StreamWriter,
        request_id: RequestId,
    ) -> None:
        """Send a session terminated error response."""
        jsonrpc_error = JSONRPCError(
            jsonrpc="2.0",
            id=request_id,
            error=ErrorData(code=32600, message="Session terminated"),
        )
        session_message = SessionMessage(JSONRPCMessage(jsonrpc_error))
        await read_stream_writer.send(session_message)

    async def post_writer(
        self,
        client: httpx.AsyncClient,
        write_stream_reader: StreamReader,
        read_stream_writer: StreamWriter,
        write_stream: MemoryObjectSendStream[SessionMessage],
        start_get_stream: Callable[[], None],
        tg: TaskGroup,
    ) -> None:
        """Handle writing requests to the server."""
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    message = session_message.message
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

                    ctx = RequestContext(
                        client=client,
                        headers=self.request_headers,
                        session_id=self.session_id,
                        session_message=session_message,
                        metadata=metadata,
                        read_stream_writer=read_stream_writer,
                        sse_read_timeout=self.sse_read_timeout,
                    )

                    async def handle_request_async():
                        if is_resumption:
                            await self._handle_resumption_request(ctx)
                        else:
                            await self._handle_post_request(ctx)

                    # If this is a request, start a new task to handle it
                    if isinstance(message.root, JSONRPCRequest):
                        tg.start_soon(handle_request_async)
                    else:
                        await handle_request_async()

        except Exception:
            logger.exception("Error in post_writer")  # pragma: no cover
        finally:
            await read_stream_writer.aclose()
            await write_stream.aclose()

    async def terminate_session(self, client: httpx.AsyncClient) -> None:  # pragma: no cover
        """Terminate the session by sending a DELETE request."""
        if not self.session_id:
            return

        try:
            headers = self._prepare_request_headers(self.request_headers)
            response = await client.delete(self.url, headers=headers)

            if response.status_code == 405:
                logger.debug("Server does not allow session termination")
            elif response.status_code not in (200, 204):
                logger.warning(f"Session termination failed: {response.status_code}")
        except Exception as exc:
            logger.warning(f"Session termination failed: {exc}")

    def get_session_id(self) -> str | None:
        """Get the current session ID."""
        return self.session_id

    async def resume_stream(
        self,
        client: httpx.AsyncClient,
        read_stream_writer: StreamWriter,
        last_event_id: str,
        on_resumption_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Resume SSE stream from a previous event ID.

        This method allows clients to reconnect and resume receiving events
        from where they left off using the Last-Event-ID header.

        Args:
            client: The HTTP client to use for the request
            read_stream_writer: Stream writer for sending received messages
            last_event_id: The last event ID received, to resume from
            on_resumption_token: Optional callback invoked with new event IDs
        """
        if not self.session_id:
            logger.warning("Cannot resume stream without a session ID")
            return

        headers = self._prepare_request_headers(self.request_headers)
        headers[LAST_EVENT_ID] = last_event_id

        try:
            async with aconnect_sse(
                client,
                "GET",
                self.url,
                headers=headers,
                timeout=httpx.Timeout(self.timeout, read=self.sse_read_timeout),
            ) as event_source:
                event_source.response.raise_for_status()
                logger.debug(f"Resumed SSE stream from event ID: {last_event_id}")  # pragma: no cover

                async for sse in event_source.aiter_sse():  # pragma: no cover
                    _is_complete, has_event_id = await self._handle_sse_event(
                        sse,
                        read_stream_writer,
                        resumption_callback=on_resumption_token,
                    )

                    # Call resumption callback if we have a new event ID
                    if has_event_id and sse.id and on_resumption_token:
                        await on_resumption_token(sse.id)

        except httpx.HTTPStatusError as exc:
            # Read response body so consumers can access error details
            try:
                await exc.response.aread()
            except Exception:
                pass  # Best effort - don't fail if we can't read body
            if exc.response.status_code == 405:
                logger.debug("Server does not support SSE resumption via GET")  # pragma: no cover
            else:
                logger.warning(f"Failed to resume stream: {exc}")
        except Exception as exc:  # pragma: no cover
            logger.debug(f"Resume stream error: {exc}")


@asynccontextmanager
async def streamablehttp_client(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float | timedelta = 30,
    sse_read_timeout: float | timedelta = 60 * 5,
    terminate_on_close: bool = True,
    httpx_client_factory: McpHttpClientFactory = create_mcp_http_client,
    auth: httpx.Auth | None = None,
    reconnection_options: StreamableHTTPReconnectionOptions | None = None,
) -> AsyncGenerator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
        GetSessionIdCallback,
    ],
    None,
]:
    """
    Client transport for StreamableHTTP.

    `sse_read_timeout` determines how long (in seconds) the client will wait for a new
    event before disconnecting. All other HTTP operations are controlled by `timeout`.
    """
    transport = StreamableHTTPTransport(url, headers, timeout, sse_read_timeout, auth, reconnection_options)

    read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)

    async with anyio.create_task_group() as tg:
        try:
            logger.debug(f"Connecting to StreamableHTTP endpoint: {url}")

            async with httpx_client_factory(
                headers=transport.request_headers,
                timeout=httpx.Timeout(transport.timeout, read=transport.sse_read_timeout),
                auth=transport.auth,
            ) as client:
                # Define callbacks that need access to tg
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
                    yield (
                        read_stream,
                        write_stream,
                        transport.get_session_id,
                    )
                finally:
                    if transport.session_id and terminate_on_close:
                        await transport.terminate_session(client)
                    tg.cancel_scope.cancel()
        finally:
            await read_stream_writer.aclose()
            await write_stream.aclose()
