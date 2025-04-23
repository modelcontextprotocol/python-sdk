"""
StreamableHTTP Client Transport Module

This module implements the StreamableHTTP transport for MCP clients,
providing support for HTTP POST requests with optional SSE streaming responses
and session management.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any

import anyio
import httpx
from httpx_sse import EventSource, aconnect_sse

from mcp.types import (
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
)

logger = logging.getLogger(__name__)

# Header names
MCP_SESSION_ID_HEADER = "mcp-session-id"
LAST_EVENT_ID_HEADER = "last-event-id"

# Content types
CONTENT_TYPE_JSON = "application/json"
CONTENT_TYPE_SSE = "text/event-stream"


@asynccontextmanager
async def streamablehttp_client(
    url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 30,
    sse_read_timeout: float = 60 * 5,
):
    """
    Client transport for StreamableHTTP.

    `sse_read_timeout` determines how long (in seconds) the client will wait for a new
    event before disconnecting. All other HTTP operations are controlled by `timeout`.

    Yields:
        Tuple of (read_stream, write_stream, terminate_callback)
    """

    read_stream_writer, read_stream = anyio.create_memory_object_stream[
        JSONRPCMessage | Exception
    ](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[
        JSONRPCMessage
    ](0)

    async with anyio.create_task_group() as tg:
        try:
            logger.info(f"Connecting to StreamableHTTP endpoint: {url}")
            # Set up headers with required Accept header
            request_headers = {
                "Accept": f"{CONTENT_TYPE_JSON}, {CONTENT_TYPE_SSE}",
                "Content-Type": CONTENT_TYPE_JSON,
                **(headers or {}),
            }

            # Track session ID if provided by server
            session_id: str | None = None

            async with httpx.AsyncClient(
                headers=request_headers, timeout=timeout, follow_redirects=True
            ) as client:

                async def post_writer():
                    nonlocal session_id
                    try:
                        async with write_stream_reader:
                            async for message in write_stream_reader:
                                # Add session ID to headers if we have one
                                post_headers = request_headers.copy()
                                if session_id:
                                    post_headers[MCP_SESSION_ID_HEADER] = session_id

                                logger.debug(f"Sending client message: {message}")

                                # Handle initial initialization request
                                is_initialization = (
                                    isinstance(message.root, JSONRPCRequest)
                                    and message.root.method == "initialize"
                                )
                                if (
                                    isinstance(message.root, JSONRPCNotification)
                                    and message.root.method
                                    == "notifications/initialized"
                                ):
                                    tg.start_soon(get_stream)

                                async with client.stream(
                                    "POST",
                                    url,
                                    json=message.model_dump(
                                        by_alias=True, mode="json", exclude_none=True
                                    ),
                                    headers=post_headers,
                                ) as response:
                                    if response.status_code == 202:
                                        logger.debug("Received 202 Accepted")
                                        continue
                                    # Check for 404 (session expired/invalid)
                                    if response.status_code == 404:
                                        if is_initialization and session_id:
                                            logger.info(
                                                "Session expired, retrying without ID"
                                            )
                                            session_id = None
                                            post_headers.pop(
                                                MCP_SESSION_ID_HEADER, None
                                            )
                                            # Retry with client.stream
                                            async with client.stream(
                                                "POST",
                                                url,
                                                json=message.model_dump(
                                                    by_alias=True,
                                                    mode="json",
                                                    exclude_none=True,
                                                ),
                                                headers=post_headers,
                                            ) as new_response:
                                                response = new_response
                                        elif isinstance(message.root, JSONRPCRequest):
                                            jsonrpc_error = JSONRPCError(
                                                jsonrpc="2.0",
                                                id=message.root.id,
                                                error=ErrorData(
                                                    code=32600,
                                                    message="Session terminated",
                                                ),
                                            )
                                            await read_stream_writer.send(
                                                JSONRPCMessage(jsonrpc_error)
                                            )
                                            continue
                                    response.raise_for_status()

                                    # Extract session ID from response headers
                                    if is_initialization:
                                        new_session_id = response.headers.get(
                                            MCP_SESSION_ID_HEADER
                                        )
                                        if new_session_id:
                                            session_id = new_session_id
                                            logger.info(
                                                f"Received session ID: {session_id}"
                                            )

                                    # Handle different response types
                                    content_type = response.headers.get(
                                        "content-type", ""
                                    ).lower()

                                    if content_type.startswith(CONTENT_TYPE_JSON):
                                        try:
                                            content = await response.aread()
                                            json_message = (
                                                JSONRPCMessage.model_validate_json(
                                                    content
                                                )
                                            )
                                            await read_stream_writer.send(json_message)
                                        except Exception as exc:
                                            logger.error(
                                                f"Error parsing JSON response: {exc}"
                                            )
                                            await read_stream_writer.send(exc)

                                    elif content_type.startswith(CONTENT_TYPE_SSE):
                                        # Parse SSE events from the response
                                        try:
                                            event_source = EventSource(response)
                                            async for sse in event_source.aiter_sse():
                                                if sse.event == "message":
                                                    try:
                                                        await read_stream_writer.send(
                                                            JSONRPCMessage.model_validate_json(
                                                                sse.data
                                                            )
                                                        )
                                                    except Exception as exc:
                                                        logger.exception(
                                                            "Error parsing message"
                                                        )
                                                        await read_stream_writer.send(
                                                            exc
                                                        )
                                                else:
                                                    logger.warning(
                                                        f"Unknown event: {sse.event}"
                                                    )

                                        except Exception as e:
                                            logger.exception(
                                                "Error reading SSE stream:"
                                            )
                                            await read_stream_writer.send(e)

                                    else:
                                        # For 202 Accepted with no body
                                        if response.status_code == 202:
                                            logger.debug("Received 202 Accepted")
                                            continue

                                        error_msg = (
                                            f"Unexpected content type: {content_type}"
                                        )
                                        logger.error(error_msg)
                                        await read_stream_writer.send(
                                            ValueError(error_msg)
                                        )

                    except Exception as exc:
                        logger.error(f"Error in post_writer: {exc}")
                    finally:
                        await read_stream_writer.aclose()
                        await write_stream.aclose()

                async def get_stream():
                    """
                    Optional GET stream for server-initiated messages
                    """
                    nonlocal session_id
                    try:
                        # Only attempt GET if we have a session ID
                        if not session_id:
                            return

                        get_headers = request_headers.copy()
                        get_headers[MCP_SESSION_ID_HEADER] = session_id

                        async with aconnect_sse(
                            client,
                            "GET",
                            url,
                            headers=get_headers,
                            timeout=httpx.Timeout(timeout, read=sse_read_timeout),
                        ) as event_source:
                            event_source.response.raise_for_status()
                            logger.debug("GET SSE connection established")

                            async for sse in event_source.aiter_sse():
                                if sse.event == "message":
                                    try:
                                        message = JSONRPCMessage.model_validate_json(
                                            sse.data
                                        )
                                        logger.debug(f"GET message: {message}")
                                        await read_stream_writer.send(message)
                                    except Exception as exc:
                                        logger.error(
                                            f"Error parsing GET message: {exc}"
                                        )
                                        await read_stream_writer.send(exc)
                                else:
                                    logger.warning(
                                        f"Unknown SSE event from GET: {sse.event}"
                                    )
                    except Exception as exc:
                        # GET stream is optional, so don't propagate errors
                        logger.debug(f"GET stream error (non-fatal): {exc}")

                tg.start_soon(post_writer)

                async def terminate_session():
                    """
                    Terminate the session by sending a DELETE request.
                    """
                    nonlocal session_id
                    if not session_id:
                        return  # No session to terminate

                    try:
                        delete_headers = request_headers.copy()
                        delete_headers[MCP_SESSION_ID_HEADER] = session_id

                        response = await client.delete(
                            url,
                            headers=delete_headers,
                        )

                        if response.status_code == 405:
                            # Server doesn't allow client-initiated termination
                            logger.debug("Server does not allow session termination")
                        elif response.status_code != 200:
                            logger.warning(
                                f"Session termination failed: {response.status_code}"
                            )
                    except Exception as exc:
                        logger.warning(f"Session termination failed: {exc}")

                try:
                    yield read_stream, write_stream, terminate_session
                finally:
                    tg.cancel_scope.cancel()
        finally:
            await read_stream_writer.aclose()
            await write_stream.aclose()
