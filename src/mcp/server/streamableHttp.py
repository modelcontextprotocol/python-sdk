"""
StreamableHTTP Server Transport Module

This module implements an HTTP transport layer with Streamable HTTP.

The transport handles bidirectional communication using HTTP requests and
responses, with streaming support for long-running operations.
"""

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
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


class StreamableHTTPServerTransport:
    """
    HTTP server transport with event streaming support for MCP.

    Handles POST requests containing JSON-RPC messages and provides
    Server-Sent Events (SSE) responses for streaming communication.
    """

    # Server notification streams for POST requests as well as standalone SSE stream
    _read_stream_writer: MemoryObjectSendStream[JSONRPCMessage | Exception] | None
    _write_stream_reader: MemoryObjectReceiveStream[JSONRPCMessage]
    # Dictionary to track request-specific message streams
    _request_streams: dict[str, MemoryObjectSendStream[JSONRPCMessage]]

    def __init__(
        self,
        mcp_session_id: str | None,
    ):
        """
        Initialize a new StreamableHTTP server transport.

        Args:
            mcp_session_id: Optional session identifier for this connection
        """
        self.mcp_session_id = mcp_session_id
        self._request_streams = {}

    async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        ASGI application entry point that handles all HTTP requests

        Args:
            stream_id: Unique identifier for this stream
            scope: ASGI scope
            receive: ASGI receive function
            send: ASGI send function
        """
        request = Request(scope, receive)

        if request.method == "POST":
            await self._handle_post_request(scope, request, receive, send)
        elif request.method == "GET":
            await self._handle_get_request(request, send)
        elif request.method == "DELETE":
            await self._handle_delete_request(request, send)
        else:
            await self._handle_unsupported_request(send)

    async def _handle_post_request(
        self, scope: Scope, request: Request, receive: Receive, send: Send
    ) -> None:
        """
        Handles POST requests containing JSON-RPC messages

        Args:
            stream_id: Unique identifier for this stream
            scope: ASGI scope
            request: Starlette Request object
            receive: ASGI receive function
            send: ASGI send function
        """
        body = await request.body()
        writer = self._read_stream_writer
        if writer is None:
            raise ValueError(
                "No read stream writer available. Ensure connect() is called first."
            )
            return
        try:
            # Validate Accept header
            accept_header = request.headers.get("accept", "")
            if (
                "application/json" not in accept_header
                or "text/event-stream" not in accept_header
            ):
                response = Response(
                    (
                        "Not Acceptable: Client must accept both application/json and "
                        "text/event-stream"
                    ),
                    status_code=406,
                    headers={"Content-Type": "application/json"},
                )
                await response(scope, receive, send)
                return

            # Validate Content-Type
            content_type = request.headers.get("content-type", "")
            if "application/json" not in content_type:
                response = Response(
                    "Unsupported Media Type: Content-Type must be application/json",
                    status_code=415,
                    headers={"Content-Type": "application/json"},
                )
                await response(scope, receive, send)
                return

            # Parse the body
            body = await request.body()
            if len(body) > MAXIMUM_MESSAGE_SIZE:
                response = Response(
                    "Payload Too Large: Message exceeds maximum size",
                    status_code=413,
                    headers={"Content-Type": "application/json"},
                )
                await response(scope, receive, send)
                return

            try:
                raw_message = json.loads(body)
            except json.JSONDecodeError as e:
                response = Response(
                    f"Parse error: {str(e)}",
                    status_code=400,
                    headers={"Content-Type": "application/json"},
                )
                await response(scope, receive, send)
                return
            message = None
            try:
                message = JSONRPCMessage.model_validate(raw_message)
            except ValidationError as e:
                response = Response(
                    f"Validation error: {str(e)}",
                    status_code=400,
                    headers={"Content-Type": "application/json"},
                )
                await response(scope, receive, send)
                return
            if not message:
                response = Response(
                    "Invalid Request: Message is empty",
                    status_code=400,
                    headers={"Content-Type": "application/json"},
                )
                await response(scope, receive, send)
                return

            # Check if this is an initialization request
            is_initialization_request = (
                isinstance(message.root, JSONRPCRequest)
                and message.root.method == "initialize"
            )

            if is_initialization_request:
                # TODO validate
                logger.info("INITIALIZATION REQUEST")
            # For non-initialization requests, validate the session
            elif not await self._validate_session(request, send):
                return

            is_request = isinstance(message.root, JSONRPCRequest)

            # For notifications and responses only, return 202 Accepted
            if not is_request:
                headers: dict[str, str] = {}
                if self.mcp_session_id:
                    headers["mcp-session-id"] = self.mcp_session_id

                # Create response object and send it
                response = Response("Accepted", status_code=202, headers=headers)
                await response(scope, receive, send)

                # Process the message after sending the response
                await writer.send(message)

                return

            # For requests, set up an SSE stream for the response
            if is_request:
                # Set up headers
                headers = {
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                }

                if self.mcp_session_id:
                    headers["mcp-session-id"] = self.mcp_session_id

                # For SSE responses, set up SSE stream
                headers["Content-Type"] = "text/event-stream"
                # Create SSE stream
                sse_stream_writer, sse_stream_reader = (
                    anyio.create_memory_object_stream[dict[str, Any]](0)
                )

                async def sse_writer():
                    try:
                        # Create a request-specific message stream for this POST request
                        request_stream_writer, request_stream_reader = (
                            anyio.create_memory_object_stream[JSONRPCMessage](0)
                        )

                        # Get the request ID from the incoming request message
                        request_id = None
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
                                if isinstance(received_message.root, JSONRPCResponse):
                                    if request_id:
                                        self._request_streams.pop(request_id, None)
                                    break
                    except Exception as e:
                        logger.exception(f"Error in SSE writer: {e}")
                    finally:
                        logger.debug("Closing SSE writer")
                        # TODO

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
                    # Make sure to clean up the request stream if something goes wrong
                    if outer_request_id and outer_request_id in self._request_streams:
                        self._request_streams.pop(outer_request_id, None)

        except Exception as err:
            logger.exception("Error handling POST request")
            response = Response(f"Error handling POST request: {err}", status_code=500)
            await response(scope, receive, send)
            if writer:
                await writer.send(err)
            return

    async def _handle_get_request(self, request: Request, send: Send) -> None:
        pass

    async def _handle_delete_request(self, request: Request, send: Send) -> None:
        pass

    async def _handle_unsupported_request(self, send: Send) -> None:
        pass

    async def _validate_session(self, request: Request, send: Send) -> bool:
        # TODO
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
        """
        Context manager that provides read and write streams for a connection

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
                # Clean up any remaining request streams
                for stream in list(self._request_streams.values()):
                    try:
                        await stream.aclose()
                    except Exception:
                        pass
                self._request_streams.clear()
