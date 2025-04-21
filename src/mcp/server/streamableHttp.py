"""
StreamableHTTP Server Transport Module

This module implements an HTTP transport layer with Streamable HTTP.

The transport handles bidirectional communication using HTTP requests and
responses, with streaming support for long-running operations.
"""

import json
import logging
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Any

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import ValidationError
from sse_starlette import EventSourceResponse
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from mcp.types import (
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)

logger = logging.getLogger(__name__)

# Maximum size for incoming messages
MAXIMUM_MESSAGE_SIZE = 4 * 1024 * 1024  # 4MB

# Header names
MCP_SESSION_ID_HEADER = "mcp-session-id"
LAST_EVENT_ID_HEADER = "last-event-id"

# Content types
CONTENT_TYPE_JSON = "application/json"
CONTENT_TYPE_SSE = "text/event-stream"

# Session ID validation pattern (visible ASCII characters ranging from 0x21 to 0x7E)
# Pattern ensures entire string contains only valid characters by using ^ and $ anchors
SESSION_ID_PATTERN = re.compile(r"^[\x21-\x7E]+$")


class StreamableHTTPServerTransport:
    """
    HTTP server transport with event streaming support for MCP.

    Handles JSON-RPC messages in HTTP POST requests with SSE streaming.
    Supports optional JSON responses and session management.
    """

    # Server notification streams for POST requests as well as standalone SSE stream
    _read_stream_writer: MemoryObjectSendStream[JSONRPCMessage | Exception] | None = (
        None
    )
    _write_stream_reader: MemoryObjectReceiveStream[JSONRPCMessage] | None = None
    # Dictionary to track request-specific message streams
    _request_streams: dict[str, MemoryObjectSendStream[JSONRPCMessage]]

    def __init__(
        self,
        mcp_session_id: str | None,
        is_json_response_enabled: bool = False,
    ) -> None:
        """
        Initialize a new StreamableHTTP server transport.

        Args:
            mcp_session_id: Optional session identifier for this connection.
                            Must contain only visible ASCII characters (0x21-0x7E).
            is_json_response_enabled: If True, return JSON responses for requests
                                    instead of SSE streams. Default is False.

        Raises:
            ValueError: If the session ID contains invalid characters.
        """
        if mcp_session_id is not None and not SESSION_ID_PATTERN.fullmatch(
            mcp_session_id
        ):
            raise ValueError(
                "Session ID must only contain visible ASCII characters (0x21-0x7E)"
            )

        self.mcp_session_id = mcp_session_id
        self.is_json_response_enabled = is_json_response_enabled
        self._request_streams = {}
        self._terminated = False

    def _create_server_response(
        self,
        message: str,
        status_code: HTTPStatus,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """Create a standardized server response."""
        response_headers = {"Content-Type": CONTENT_TYPE_JSON}
        if headers:
            response_headers.update(headers)

        if self.mcp_session_id:
            response_headers[MCP_SESSION_ID_HEADER] = self.mcp_session_id

        return Response(
            message,
            status_code=status_code,
            headers=response_headers,
        )

    def _create_json_response(
        self,
        response_message: JSONRPCMessage,
        status_code: HTTPStatus = HTTPStatus.OK,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """Create a JSON response from a JSONRPCMessage"""
        response_headers = {"Content-Type": CONTENT_TYPE_JSON}
        if headers:
            response_headers.update(headers)

        if self.mcp_session_id:
            response_headers[MCP_SESSION_ID_HEADER] = self.mcp_session_id

        return Response(
            response_message.model_dump_json(by_alias=True, exclude_none=True),
            status_code=status_code,
            headers=response_headers,
        )

    def _get_session_id(self, request: Request) -> str | None:
        """Extract the session ID from request headers."""
        return request.headers.get(MCP_SESSION_ID_HEADER)

    async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Application entry point that handles all HTTP requests"""
        request = Request(scope, receive)
        if self._terminated:
            # If the session has been terminated, return 404 Not Found
            response = self._create_server_response(
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

    def _check_accept_headers(self, request: Request) -> tuple[bool, bool]:
        """Check if the request accepts the required media types."""
        accept_header = request.headers.get("accept", "")
        accept_types = [media_type.strip() for media_type in accept_header.split(",")]

        has_json = any(
            media_type.startswith(CONTENT_TYPE_JSON) for media_type in accept_types
        )
        has_sse = any(
            media_type.startswith(CONTENT_TYPE_SSE) for media_type in accept_types
        )

        return has_json, has_sse

    def _check_content_type(self, request: Request) -> bool:
        """Check if the request has the correct Content-Type."""
        content_type = request.headers.get("content-type", "")
        content_type_parts = [
            part.strip() for part in content_type.split(";")[0].split(",")
        ]

        return any(part == CONTENT_TYPE_JSON for part in content_type_parts)

    async def _handle_post_request(
        self, scope: Scope, request: Request, receive: Receive, send: Send
    ) -> None:
        """Handle POST requests containing JSON-RPC messages."""
        writer = self._read_stream_writer
        if writer is None:
            raise ValueError(
                "No read stream writer available. Ensure connect() is called first."
            )
        try:
            # Check Accept headers
            has_json, has_sse = self._check_accept_headers(request)
            if not (has_json and has_sse):
                response = self._create_server_response(
                    (
                        "Not Acceptable: Client must accept both application/json and "
                        "text/event-stream"
                    ),
                    HTTPStatus.NOT_ACCEPTABLE,
                )
                await response(scope, receive, send)
                return

            # Validate Content-Type
            if not self._check_content_type(request):
                response = self._create_server_response(
                    "Unsupported Media Type: Content-Type must be application/json",
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                )
                await response(scope, receive, send)
                return

            # Parse the body - only read it once
            body = await request.body()
            if len(body) > MAXIMUM_MESSAGE_SIZE:
                response = self._create_server_response(
                    "Payload Too Large: Message exceeds maximum size",
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
                await response(scope, receive, send)
                return

            try:
                raw_message = json.loads(body)
            except json.JSONDecodeError as e:
                response = self._create_server_response(
                    f"Parse error: {str(e)}",
                    HTTPStatus.BAD_REQUEST,
                )
                await response(scope, receive, send)
                return

            try:
                message = JSONRPCMessage.model_validate(raw_message)
            except ValidationError as e:
                response = self._create_server_response(
                    f"Validation error: {str(e)}",
                    HTTPStatus.BAD_REQUEST,
                )
                await response(scope, receive, send)
                return

            # Check if this is an initialization request
            is_initialization_request = (
                isinstance(message.root, JSONRPCRequest)
                and message.root.method == "initialize"
            )

            if is_initialization_request:
                # Check if the server already has an established session
                if self.mcp_session_id:
                    # Check if request has a session ID
                    request_session_id = self._get_session_id(request)

                    # If request has a session ID but doesn't match, return 404
                    if request_session_id and request_session_id != self.mcp_session_id:
                        response = self._create_server_response(
                            "Not Found: Invalid or expired session ID",
                            HTTPStatus.NOT_FOUND,
                        )
                        await response(scope, receive, send)
                        return
            # For non-initialization requests, validate the session
            elif not await self._validate_session(request, send):
                return

            is_request = isinstance(message.root, JSONRPCRequest)

            # For notifications and responses only, return 202 Accepted
            if not is_request:
                # Create response object and send it
                response = self._create_server_response(
                    "Accepted",
                    HTTPStatus.ACCEPTED,
                )
                await response(scope, receive, send)

                # Process the message after sending the response
                await writer.send(message)

                return

            # For requests, determine whether to return JSON or set up SSE stream
            if is_request:
                if self.is_json_response_enabled:
                    # JSON response mode - create a response future
                    request_id = None
                    if isinstance(message.root, JSONRPCRequest):
                        request_id = str(message.root.id)

                    if not request_id:
                        # Should not happen for valid JSONRPCRequest, but handle it
                        response = self._create_server_response(
                            "Invalid Request: Missing request ID",
                            HTTPStatus.BAD_REQUEST,
                        )
                        await response(scope, receive, send)
                        return

                    # Create promise stream for getting response
                    request_stream_writer, request_stream_reader = (
                        anyio.create_memory_object_stream[JSONRPCMessage](0)
                    )

                    # Register this stream for the request ID
                    self._request_streams[request_id] = request_stream_writer

                    # Process the message
                    await writer.send(message)

                    try:
                        # Process messages from the request-specific stream
                        # We need to collect all messages until we get a response
                        response_message = None

                        # Use similar approach to SSE writer for consistency
                        async for received_message in request_stream_reader:
                            # If it's a response, this is what we're waiting for
                            if isinstance(received_message.root, JSONRPCResponse):
                                response_message = received_message
                                break
                            # For notifications, keep waiting for the actual response
                            elif isinstance(received_message.root, JSONRPCNotification):
                                # Just process it and continue waiting
                                logger.debug(
                                    f"Notification: {received_message.root.method}"
                                )

                        # At this point we should have a response
                        if response_message:
                            # Create JSON response
                            response = self._create_json_response(response_message)
                            await response(scope, receive, send)
                        else:
                            # This shouldn't happen in normal operation
                            logger.error(
                                "No response message received before stream closed"
                            )
                            response = self._create_server_response(
                                "Error processing request: No response received",
                                HTTPStatus.INTERNAL_SERVER_ERROR,
                            )
                            await response(scope, receive, send)
                    except Exception as e:
                        logger.exception(f"Error processing JSON response: {e}")
                        response = self._create_server_response(
                            f"Error processing request: {str(e)}",
                            HTTPStatus.INTERNAL_SERVER_ERROR,
                        )
                        await response(scope, receive, send)
                    finally:
                        # Clean up the request stream
                        if request_id in self._request_streams:
                            self._request_streams.pop(request_id, None)
                        await request_stream_reader.aclose()
                        await request_stream_writer.aclose()
                else:
                    # SSE stream mode (original behavior)
                    # Set up headers
                    headers = {
                        "Cache-Control": "no-cache, no-transform",
                        "Connection": "keep-alive",
                        "Content-Type": CONTENT_TYPE_SSE,
                    }

                    if self.mcp_session_id:
                        headers[MCP_SESSION_ID_HEADER] = self.mcp_session_id
                    # Create SSE stream
                    sse_stream_writer, sse_stream_reader = (
                        anyio.create_memory_object_stream[dict[str, Any]](0)
                    )

                    async def sse_writer():
                        # Get the request ID from the incoming request message
                        request_id = None
                        try:
                            # Create a request-specific message stream for this POST
                            request_stream_writer, request_stream_reader = (
                                anyio.create_memory_object_stream[JSONRPCMessage](0)
                            )

                            if isinstance(message.root, JSONRPCRequest):
                                request_id = str(message.root.id)
                                # Register this stream for the request ID
                                if request_id:
                                    self._request_streams[request_id] = (
                                        request_stream_writer
                                    )

                            async with sse_stream_writer, request_stream_reader:
                                # Process messages from the request-specific stream
                                async for received_message in request_stream_reader:
                                    # Send the message via SSE
                                    related_request_id = None

                                    if isinstance(
                                        received_message.root, JSONRPCNotification
                                    ):
                                        # Get related_request_id from params
                                        params = received_message.root.params
                                        if params and "related_request_id" in params:
                                            related_request_id = params.get(
                                                "related_request_id"
                                            )
                                            logger.debug(
                                                f"NOTIFICATION: {related_request_id}, "
                                                f"{params.get('data')}"
                                            )

                                    # Build the event data
                                    event_data = {
                                        "event": "message",
                                        "data": received_message.model_dump_json(
                                            by_alias=True, exclude_none=True
                                        ),
                                    }

                                    await sse_stream_writer.send(event_data)

                                    # If response, remove from pending streams and close
                                    if isinstance(
                                        received_message.root, JSONRPCResponse
                                    ):
                                        if request_id:
                                            self._request_streams.pop(request_id, None)
                                        break
                        except Exception as e:
                            logger.exception(f"Error in SSE writer: {e}")
                        finally:
                            logger.debug("Closing SSE writer")
                            # Clean up the request-specific streams
                            if request_id and request_id in self._request_streams:
                                self._request_streams.pop(request_id, None)

                    # Create and start EventSourceResponse
                    response = EventSourceResponse(
                        content=sse_stream_reader,
                        data_sender_callable=sse_writer,
                        headers=headers,
                    )

                    # Extract the request ID outside the try block for proper scope
                    outer_request_id = None
                    if isinstance(message.root, JSONRPCRequest):
                        outer_request_id = str(message.root.id)

                    # Start the SSE response (this will send headers immediately)
                    try:
                        # First send the response to establish the SSE connection
                        async with anyio.create_task_group() as tg:
                            tg.start_soon(response, scope, receive, send)

                            # Then send the message to be processed by the server
                            await writer.send(message)
                    except Exception:
                        logger.exception("SSE response error")
                        # Clean up the request stream if something goes wrong
                        if (
                            outer_request_id
                            and outer_request_id in self._request_streams
                        ):
                            self._request_streams.pop(outer_request_id, None)

        except Exception as err:
            logger.exception("Error handling POST request")
            response = self._create_server_response(
                f"Error handling POST request: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            await response(scope, receive, send)
            if writer:
                await writer.send(err)
            return

    async def _handle_get_request(self, request: Request, send: Send) -> None:
        """Handle GET requests for SSE stream establishment."""
        # Validate session ID if server has one
        if not await self._validate_session(request, send):
            return
        # Validate Accept header - must include text/event-stream
        _, has_sse = self._check_accept_headers(request)

        if not has_sse:
            response = self._create_server_response(
                "Not Acceptable: Client must accept text/event-stream",
                HTTPStatus.NOT_ACCEPTABLE,
            )
            await response(request.scope, request.receive, send)
            return

        # TODO: Implement SSE stream for GET requests
        # For now, return 405 Method Not Allowed
        response = self._create_server_response(
            "SSE stream from GET request not implemented yet",
            HTTPStatus.METHOD_NOT_ALLOWED,
        )
        await response(request.scope, request.receive, send)

    async def _handle_delete_request(self, request: Request, send: Send) -> None:
        """Handle DELETE requests for explicit session termination."""
        # Validate session ID
        if not self.mcp_session_id:
            # If no session ID set, return Method Not Allowed
            response = self._create_server_response(
                "Method Not Allowed: Session termination not supported",
                HTTPStatus.METHOD_NOT_ALLOWED,
            )
            await response(request.scope, request.receive, send)
            return

        if not await self._validate_session(request, send):
            return

        self._terminate_session()

        response = self._create_server_response(
            "Session terminated",
            HTTPStatus.OK,
        )
        await response(request.scope, request.receive, send)

    def _terminate_session(self) -> None:
        """Terminate the current session, closing all streams.

        Once terminated, all requests with this session ID will receive 404 Not Found.
        """

        self._terminated = True
        logger.info(f"Terminating session: {self.mcp_session_id}")

        # We need a copy of the keys to avoid modification during iteration
        request_stream_keys = list(self._request_streams.keys())

        # Close all request streams (synchronously)
        for key in request_stream_keys:
            try:
                # Get the stream
                stream = self._request_streams.get(key)
                if stream:
                    # We must use close() here, not aclose() since this is a sync method
                    stream.close()
            except Exception as e:
                logger.debug(f"Error closing stream {key} during termination: {e}")

        # Clear the request streams dictionary immediately
        self._request_streams.clear()

    async def _handle_unsupported_request(self, request: Request, send: Send) -> None:
        """Handle unsupported HTTP methods."""
        headers = {
            "Content-Type": CONTENT_TYPE_JSON,
            "Allow": "GET, POST, DELETE",
        }
        if self.mcp_session_id:
            headers[MCP_SESSION_ID_HEADER] = self.mcp_session_id

        response = Response(
            "Method Not Allowed",
            status_code=HTTPStatus.METHOD_NOT_ALLOWED,
            headers=headers,
        )
        await response(request.scope, request.receive, send)

    async def _validate_session(self, request: Request, send: Send) -> bool:
        """Validate the session ID in the request."""
        if not self.mcp_session_id:
            # If we're not using session IDs, return True
            return True

        # Get the session ID from the request headers
        request_session_id = self._get_session_id(request)

        # If no session ID provided but required, return error
        if not request_session_id:
            response = self._create_server_response(
                "Bad Request: Missing session ID",
                HTTPStatus.BAD_REQUEST,
            )
            await response(request.scope, request.receive, send)
            return False

        # If session ID doesn't match, return error
        if request_session_id != self.mcp_session_id:
            response = self._create_server_response(
                "Not Found: Invalid or expired session ID",
                HTTPStatus.NOT_FOUND,
            )
            await response(request.scope, request.receive, send)
            return False

        return True

    @asynccontextmanager
    async def connect(
        self,
    ) -> AsyncGenerator[
        tuple[
            MemoryObjectReceiveStream[JSONRPCMessage | Exception],
            MemoryObjectSendStream[JSONRPCMessage],
        ],
        None,
    ]:
        """Context manager that provides read and write streams for a connection.

        Yields:
            Tuple of (read_stream, write_stream) for bidirectional communication
        """

        # Create the memory streams for this connection
        read_stream: MemoryObjectReceiveStream[JSONRPCMessage | Exception]
        read_stream_writer: MemoryObjectSendStream[JSONRPCMessage | Exception]

        write_stream: MemoryObjectSendStream[JSONRPCMessage]
        write_stream_reader: MemoryObjectReceiveStream[JSONRPCMessage]

        read_stream_writer, read_stream = anyio.create_memory_object_stream[
            JSONRPCMessage | Exception
        ](0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream[
            JSONRPCMessage
        ](0)

        # Store the streams
        self._read_stream_writer = read_stream_writer
        self._write_stream_reader = write_stream_reader

        # Start a task group for message routing
        async with anyio.create_task_group() as tg:
            # Create a message router that distributes messages to request streams
            async def message_router():
                try:
                    async for message in write_stream_reader:
                        # Determine which request stream(s) should receive this message
                        target_request_id = None

                        # For responses, route based on the request ID
                        if isinstance(message.root, JSONRPCResponse):
                            target_request_id = str(message.root.id)
                        # For notifications, route by related_request_id if available
                        elif isinstance(message.root, JSONRPCNotification):
                            # Get related_request_id from params
                            params = message.root.params
                            if params and "related_request_id" in params:
                                related_id = params.get("related_request_id")
                                if related_id is not None:
                                    target_request_id = str(related_id)

                        # Send to the specific request stream if available
                        if (
                            target_request_id
                            and target_request_id in self._request_streams
                        ):
                            try:
                                await self._request_streams[target_request_id].send(
                                    message
                                )
                            except (
                                anyio.BrokenResourceError,
                                anyio.ClosedResourceError,
                            ):
                                # Stream might be closed, remove from registry
                                self._request_streams.pop(target_request_id, None)
                except Exception as e:
                    logger.exception(f"Error in message router: {e}")

            # Start the message router
            tg.start_soon(message_router)

            try:
                # Yield the streams for the caller to use
                yield read_stream, write_stream
            finally:
                for stream in list(self._request_streams.values()):
                    try:
                        await stream.aclose()
                    except Exception:
                        pass
                self._request_streams.clear()
