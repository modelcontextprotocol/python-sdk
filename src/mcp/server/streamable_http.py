"""
Streamable HTTP Transport Module for MCP Server

This module provides an implementation of the MCP Streamable HTTP transport
specification for server-side communication as defined in protocol revision 2025-03-26.
"""

import logging
import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
import json
import uuid
from typing import Dict, Optional, Callable, Union, Set, Any, Tuple
from contextlib import asynccontextmanager

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from mcp.types import JSONRPCMessage

logger = logging.getLogger(__name__)


class StreamableHTTPServerTransport:
    """
    Streamable HTTP server transport for MCP. This class provides an ASGI application
    suitable to be used with a framework like Starlette and a server like Uvicorn.

    The transport implements the MCP Streamable HTTP transport specification, which
    enables full-duplex communication over HTTP with Server-Sent Events (SSE) for
    streaming from server to client.
    """

    def __init__(
        self,
        session_id_generator: Optional[Callable[[], Optional[str]]] = None,
    ):
        """Initialize a new StreamableHTTPServerTransport.
        
        Args:
            session_id_generator: Optional function to generate session IDs.
                If None (default), the transport operates in stateless mode with no session tracking.
                To enable stateful mode, provide a function that returns string IDs.
                The session ID SHOULD be globally unique and cryptographically secure
                (e.g., a securely generated UUID, a JWT, or a cryptographic hash).
                The session ID MUST only contain visible ASCII characters (ranging from 0x21 to 0x7E).
        """
        # Default to None (stateless) if not provided
        self._session_id_generator = session_id_generator
        self._connections: Dict[str, MemoryObjectSendStream] = {}
        self._started = False
        self._initialized = False
        
        # Session management (only used if session_id_generator is provided)
        self._session_id = None
        self._active_sessions: Set[str] = set()
        
        # Add request tracking - only needed for targeted routing
        self._request_connections: Dict[str, str] = {}
        
        # Track the last event ID for resumability
        self._stream_event_ids: Dict[str, Dict[str, str]] = {}  # connection_id -> {event_id -> message_id}

        # Callbacks
        self.onmessage: Optional[Callable[[JSONRPCMessage], None]] = None
        self.onerror: Optional[Callable[[Exception], None]] = None
        self.onclose: Optional[Callable[[], None]] = None

    async def start(self):
        """Initialize the transport."""
        if self._started:
            raise RuntimeError("Transport already started")
        self._started = True
        logger.debug("Streamable HTTP transport started")

    @asynccontextmanager
    async def connect_streamable_http(self, scope: Scope, receive: Receive, send: Send):
        """Set up a connection for Streamable HTTP."""
        try:
            if scope["type"] != "http":
                raise ValueError("connect_streamable_http can only handle HTTP requests")
                
            request = Request(scope, receive)
            connection_id = str(uuid.uuid4())
            
            # Validate Origin header
            if not request.headers.get("origin"):
                await self._send_error(send, 400, "Origin header is required")
                return
            
            # Create streams for message passing
            logger.debug(f"Setting up Streamable HTTP connection")
            read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
            write_stream, write_stream_reader = anyio.create_memory_object_stream(0)
            
            # Process based on HTTP method
            success = False
            if request.method == "GET":
                # For GET requests, set up SSE stream
                success = await self._handle_get(request, send, connection_id)
            elif request.method == "POST":
                # For POST requests, process the request body
                success = await self._handle_post(request, send, read_stream_writer)
            elif request.method == "DELETE":
                # For DELETE requests, terminate the session
                success = await self._handle_delete(request, send)
            else:
                # Reject other methods
                await self._send_error(send, 405, "Method not allowed", headers={"Allow": "GET, POST, DELETE"})
            
            if not success:
                return
                
            try:
                # Yield the streams to the caller
                yield (read_stream, write_stream)
                
                # For GET requests, handle SSE streaming
                if request.method == "GET":
                    async with anyio.create_task_group() as tg:
                        async def stream_responses():
                            try:
                                async for event_id, response in write_stream_reader:
                                    await self._send_sse_event(send, event_id, response, connection_id)
                            except (anyio.EndOfStream, anyio.ClosedResourceError):
                                pass
                            except Exception as e:
                                logger.debug(f"SSE connection closed: {e}")
                        
                        tg.start_soon(stream_responses)
                        
                        # Keep SSE connection open until client disconnects
                        try:
                            message = await receive()
                            while message["type"] != "http.disconnect":
                                message = await receive()
                        except Exception as e:
                            logger.debug(f"SSE connection closed: {e}")
            finally:
                # Clean up resources
                if connection_id in self._connections:
                    try:
                        # Try to close the connection
                        if self._connections.get(connection_id):
                            await self._connections[connection_id].aclose()
                    except (anyio.EndOfStream, anyio.ClosedResourceError):
                        pass
                    except Exception as e:
                        logger.debug(f"Error closing connection: {e}")
                    finally:
                        # Remove connection from tracking
                        self._connections.pop(connection_id, None)
                    
                # Clean up event ID tracking
                self._stream_event_ids.pop(connection_id, None)
                    
                # Close streams
                try:
                    await read_stream_writer.aclose()
                except (anyio.EndOfStream, anyio.ClosedResourceError):
                    pass
                
                try:
                    await write_stream.aclose()
                except (anyio.EndOfStream, anyio.ClosedResourceError):
                    pass
        except Exception as e:
            logger.error(f"Connection error: {e}")
            if self.onerror:
                self.onerror(e)
            raise

    async def _send_sse_event(self, send: Send, event_id: str, message: Any, connection_id: str):
        """Format and send a Server-Sent Event."""
        # Track event ID for resumability
        if connection_id not in self._stream_event_ids:
            self._stream_event_ids[connection_id] = {}
        
        # Store event ID mapping
        if isinstance(message, dict) and "id" in message:
            self._stream_event_ids[connection_id][event_id] = message["id"]
        
        # Format as standard SSE event
        sse_data = []
        if event_id:
            sse_data.append(f"id: {event_id}")
        
        sse_data.append("event: message")
        
        # Format message data
        message_json = json.dumps(message)
        for line in message_json.splitlines():
            sse_data.append(f"data: {line}")
        
        # End with blank line
        sse_data.append("")
        sse_data.append("")
        
        # Send to client
        await send({
            "type": "http.response.body",
            "body": "\n".join(sse_data).encode(),
            "more_body": True
        })

    async def _handle_get(self, request: Request, send: Send, connection_id: str) -> bool:
        """Handle GET requests for SSE streaming.
        
        According to the spec, GET requests are used to open an SSE stream,
        allowing the server to communicate to the client without the client 
        first sending data via HTTP POST.
        """
        # Check if session ID is required and valid
        if not self._validate_session(request):
            await self._send_error(send, 404, "Session not found")
            return False

        # Validate Accept header contains text/event-stream per spec
        accept = request.headers.get("accept", "")
        if "text/event-stream" not in accept:
            await self._send_error(send, 406, "Accept must include text/event-stream", 
                                  headers={"Accept": "text/event-stream"})
            return False
        
        # Check for Last-Event-ID header to support resumability
        last_event_id = request.headers.get("last-event-id")
        
        # Set up SSE connection with required headers
        headers = [
            (b"content-type", b"text/event-stream"),  # Required for SSE
            (b"cache-control", b"no-cache"),          # Prevents caching
            (b"connection", b"keep-alive")            # Keeps connection open
        ]
        
        # Add session ID if available
        if self.session_id:
            headers.append((b"mcp-session-id", self.session_id.encode()))
        
        
        # Send initial headers - start of SSE stream
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": headers
        })
        
        # Create a channel for this connection
        send_stream, receive_stream = anyio.create_memory_object_stream(max_buffer_size=10)
        self._connections[connection_id] = send_stream
        
        # Send initial empty chunk to establish stream
        await send({
            "type": "http.response.body",
            "body": b":\n\n",  # SSE comment format for keep-alive
            "more_body": True
        })
        
        # If Last-Event-ID was provided, replay messages as appropriate
        if last_event_id:
            await self._handle_stream_resumption(last_event_id, connection_id)
        
        return True

    async def _handle_stream_resumption(self, last_event_id: str, connection_id: str):
        """Handle resumption of a stream after disconnection."""
        # This is a simplified implementation - in a real-world scenario
        # you would want to store messages in a more persistent way
        logger.debug(f"Stream resumption requested with last event ID: {last_event_id}")
        
        # In a complete implementation, we would retrieve and replay
        # messages that were sent after the last event ID
        # This requires a more sophisticated storage mechanism
        pass

    async def _handle_post(self, request: Request, send: Send, read_stream_writer) -> bool:
        """Handle POST requests with JSON-RPC messages.
        
        According to the spec:
        - Every JSON-RPC message sent from the client MUST be a new HTTP POST request
        - If the input consists solely of JSON-RPC responses or notifications, return 202 Accepted
        - If the input contains any JSON-RPC requests, return either text/event-stream or application/json
        """
        try:
            # Validate headers
            content_type = request.headers.get("content-type", "")
            accept = request.headers.get("accept", "")
            
            # Validate content-type is application/json
            if "application/json" not in content_type:
                await self._send_error(send, 415, "Content-Type must be application/json")
                return False
            
            # Validate accept includes application/json and text/event-stream
            if "application/json" not in accept or "text/event-stream" not in accept:
                await self._send_error(send, 406, "Accept must include application/json and text/event-stream")
                return False
            
            # Parse body
            body = await request.body()
            data = json.loads(body)
            is_batch = isinstance(data, list)
            messages = data if is_batch else [data]
            
            # Generate a connection ID for tracking request IDs
            connection_id = str(uuid.uuid4())
            
            # Create a connection stream for sending responses
            send_stream, receive_stream = anyio.create_memory_object_stream(max_buffer_size=10)
            self._connections[connection_id] = send_stream
            
            # Track request IDs that need responses
            for msg in messages:
                if isinstance(msg, dict) and "method" in msg and "id" in msg:
                    self._request_connections[msg["id"]] = connection_id
            
            # Check if this is an initialization request
            is_init = any(msg.get("method") == "initialize" for msg in messages if isinstance(msg, dict))
            
            if is_init:
                # Special handling for initialization
                if self._initialized:
                    await self._send_error(send, 400, "Server already initialized")
                    return False
                
                # Initialization can't be batched
                if len(messages) > 1:
                    await self._send_error(send, 400, "Initialization cannot be batched")
                    return False
                
                # Set up session if session management is enabled
                if self._session_id_generator:
                    self.session_id = self._session_id_generator()
                    if self.session_id:
                        self._active_sessions.add(self.session_id)
            
                self._initialized = True
                
                # Send JSON response with session ID
                headers = [(b"content-type", b"application/json")]
                if self.session_id:
                    headers.append((b"mcp-session-id", self.session_id.encode()))
                
                # Send response
                await send({
                    "type": "http.response.start",
                    "status": 200,
                    "headers": headers
                })
                
                await send({
                    "type": "http.response.body",
                    "body": b"",
                    "more_body": False
                })
            else:
                # All other requests (non-initialization)
                # Check if contains any requests, or only notifications/responses
                has_requests = any("method" in msg and "id" in msg for msg in messages if isinstance(msg, dict))
                
                if not has_requests:
                    # If input consists solely of JSON-RPC responses or notifications:
                    # The server MUST return HTTP status code 202 Accepted with no body.
                    status = 202
                    content_type = "application/json"
                    response_body = b""
                else:
                    # For requests (with IDs), we need to decide if we respond with SSE or JSON
                    simple_methods = ["ping", "list_tools", "get_specification"]
                    all_simple = all(msg.get("method") in simple_methods 
                                   for msg in messages 
                                   if isinstance(msg, dict) and "id" in msg and "method" in msg)

                    # Use application/json for simple methods if client accepts it first
                    prefer_json = "application/json" in accept.split(",")[0]
                    
                    if all_simple and prefer_json:
                        # Return a simple JSON response
                        status = 200
                        content_type = "application/json"
                        
                        # For simple methods, we can respond immediately
                        if is_batch:
                            # Create a batch response with empty results
                            responses = [
                                {
                                    "jsonrpc": "2.0",
                                    "result": {},
                                    "id": msg.get("id")
                                }
                                for msg in messages
                                if isinstance(msg, dict) and "id" in msg
                            ]
                            response_body = json.dumps(responses).encode()
                        else:
                            # Single response
                            response_body = json.dumps({
                                "jsonrpc": "2.0",
                                "result": {},
                                "id": messages[0].get("id") if isinstance(messages[0], dict) else None
                            }).encode()
                    else:
                        # Default to SSE for all complex methods
                        status = 200
                        content_type = "text/event-stream"
                        response_body = b""
                
                # Set up headers
                headers = [(b"content-type", content_type.encode())]
                if self.session_id:
                    headers.append((b"mcp-session-id", self.session_id.encode()))
                
                # Send response
                await send({
                    "type": "http.response.start",
                    "status": status,
                    "headers": headers
                })
                
                await send({
                    "type": "http.response.body",
                    "body": response_body,
                    "more_body": content_type == "text/event-stream"
                })
            # Process all messages through the transport
            for msg in messages:
                await read_stream_writer.send(msg)
            
            return True
            
        except json.JSONDecodeError:
            await self._send_error(send, 400, "Parse error", code=-32700)
            return False
        except Exception as e:
            logger.error(f"POST error: {e}")
            await self._send_error(send, 500, "Internal server error")
            return False

    async def _handle_delete(self, request: Request, send: Send) -> bool:
        """Handle DELETE requests for session termination."""
        # Validate session
        if not self._validate_session(request):
            await self._send_error(send, 404, "Session not found")
            return False
        
        # Remove session from active sessions if present
        session_id = request.headers.get("mcp-session-id")
        if session_id and session_id in self._active_sessions:
            self._active_sessions.remove(session_id)
            logger.debug(f"Session {session_id} terminated by client request")
        
        # Send success response
        headers = []
        
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": headers
        })
        
        await send({
            "type": "http.response.body",
            "body": b"",
            "more_body": False
        })
        
        return True

    async def _send_error(self, send: Send, status: int, message: str, code: int = -32000, data: Any = None, headers: Dict[str, str] = None):
        """Send a JSON-RPC error response with specific error code."""
        body = {
            "jsonrpc": "2.0",
            "error": {
                "code": code,
                "message": message
            },
            "id": None
        }
        
        if data:
            body["error"]["data"] = data
        
        h = [(b"content-type", b"application/json")]
        
        # Add additional headers
        if headers:
            for key, value in headers.items():
                h.append((key.encode(), value.encode()))
        
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": h
        })
        
        await send({
            "type": "http.response.body",
            "body": json.dumps(body).encode(),
            "more_body": False
        })

    def _validate_session(self, request: Request) -> bool:
        """Validate the session ID in a request.
        
        According to the MCP specification:
        - In stateless mode, all requests are valid (no session ID needed)
        - In stateful mode, request must include a valid session ID
        - SSE connections are always allowed during initialization
        """
        is_sse = request.method == "GET" and "text/event-stream" in request.headers.get("accept", "")
        
        # During initialization, only allow SSE 
        if not self._initialized:
            # Allow SSE connections even before full initialization, clients often open SSE right after sending init
            return is_sse
        
        # Check if we're in stateless mode 
        if self._session_id_generator is None or self.session_id is None:
            # In stateless mode, all requests are valid
            logger.debug("Operating in stateless mode, all requests are valid")
            return True
        
        # We're in stateful mode - validate the client's session ID
        client_sid = request.headers.get("mcp-session-id")
        if not client_sid:
            logger.debug(f"Session ID required in stateful mode but not provided")
            return False
        
        # Check if the session ID matches and is active
        is_valid = client_sid == self.session_id and client_sid in self._active_sessions
        if not is_valid:
            logger.debug(f"Invalid session ID: {client_sid}, expected: {self.session_id}")
        
        return is_valid

    async def close(self):
        """Close the transport and release all resources."""
        logger.debug("Closing Streamable HTTP transport")
        
        # Close all connections
        for send_stream in list(self._connections.values()):
            try:
                await send_stream.aclose()
            except (anyio.EndOfStream, anyio.ClosedResourceError):
                pass
        
        # Clear state
        self._connections.clear()
        self._stream_event_ids.clear()
        
        # Clean up session
        if self.session_id and self.session_id in self._active_sessions:
            self._active_sessions.remove(self.session_id)
        
        # Call onclose
        if self.onclose:
            self.onclose()

    async def handle_http(self, scope: Scope, receive: Receive, send: Send):
        """Handle HTTP request as an ASGI application."""
        async with self.connect_streamable_http(scope, receive, send) as streams:
            if streams is None:
                return  # Error already handled
            
            read_stream, write_stream = streams
            
            # Get the request method
            request = Request(scope)
            method = request.method
            
            try:
                # For POST requests with IDs, we need to process all messages and wait for responses
                async with anyio.create_task_group() as tg:
                    # Process messages from client
                    async def process_messages():
                        try:
                            received_messages = []
                            async for message in read_stream:
                                if isinstance(message, Exception):
                                    if self.onerror:
                                        self.onerror(message)
                                else:
                                    received_messages.append(message)
                                    # Process the message through the server
                                    if self.onmessage:
                                        # Await the response from the message handler
                                        response = await self.onmessage(message)
                                        
                                        # If there's a response, send it back
                                        if response:
                                            logger.debug(f"Got response: {response}")
                                            await self.send(response)
                        
                            # All messages processed
                            logger.debug(f"Processed {len(received_messages)} messages, method={method}")
                        except Exception as e:
                            logger.error(f"Message processing error: {e}")
                            if self.onerror:
                                self.onerror(e)
                
                    # Start processing messages
                    tg.start_soon(process_messages)
                    
                    # For GET requests (SSE), we need to keep the connection open until client disconnects
                    if method == "GET":
                        try:
                            # Wait for client disconnect
                            message = await receive()
                            while message["type"] != "http.disconnect":
                                message = await receive()
                        except Exception as e:
                            logger.debug(f"SSE connection closed: {e}")
                    
                    # For POST requests, if not using SSE, we wait for the message processing to complete
                    if method == "POST":
                        # The task completes when all messages have been processed and responses generated
                        pass  # Just let the task group handle it
                
            except Exception as e:
                logger.error(f"HTTP handling error: {e}")
                if self.onerror:
                    self.onerror(e)

    @property
    def session_id(self) -> Optional[str]:
        """Get the current session ID."""
        return self._session_id if hasattr(self, "_session_id") else None
        
    @session_id.setter
    def session_id(self, value: Optional[str]):
        """Set the session ID."""
        self._session_id = value

    async def send(self, message, event_id=None):
        """Send a message to the appropriate client connection(s).
        
        Args:
            message: The JSON-RPC message to send.
            event_id: Optional event ID for SSE. If not provided, a UUID will be generated.
        """
        if event_id is None:
            event_id = str(uuid.uuid4())
            
        # Check if this is a response to a specific request
        is_response = False
        target_connection = None
        msg_id = None
        
        # First, determine if this is a response message
        if isinstance(message, dict) and "id" in message and message["id"] is not None:
            msg_id = message["id"]
            is_response = True
            
            # If we have a mapping from this request ID to a connection, use it
            if msg_id in self._request_connections:
                target_connection = self._request_connections[msg_id]
        
        # Log what's happening for debugging
        logger.debug(f"Sending message: is_response={is_response}, id={msg_id}, target={target_connection}, connections={list(self._connections.keys())}")
        
        # Case 1: Response with known target connection - send directly
        if is_response and target_connection in self._connections:
            try:
                # Send to specific connection
                await self._connections[target_connection].send((event_id, message))
                # Clean up the request tracking
                self._request_connections.pop(msg_id, None)
                return True
            except (anyio.ClosedResourceError, anyio.EndOfStream):
                # Connection closed, remove it
                self._connections.pop(target_connection, None)
                logger.warning(f"Connection {target_connection} closed, couldn't deliver response for request {msg_id}")
                return False
        
        # Case 2: Non-response message (notification, request) - broadcast to all
        elif not is_response:
            success = False
            for conn_id, send_stream in list(self._connections.items()):
                try:
                    await send_stream.send((event_id, message))
                    success = True  # Set true if at least one connection received it
                except (anyio.ClosedResourceError, anyio.EndOfStream):
                    self._connections.pop(conn_id, None)
            return success
        
        # Case 3: Response but no specific target (stateless mode or connection lost)
        # In stateless mode, we might not have a connection mapping, so try all connections
        elif is_response and len(self._connections) > 0:
            # Try sending to all connections as a fallback for stateless operation
            logger.debug(f"No specific target for response ID {msg_id}, trying all connections")
            success = False
            for conn_id, send_stream in list(self._connections.items()):
                try:
                    await send_stream.send((event_id, message))
                    success = True
                    if msg_id in self._request_connections:
                        self._request_connections.pop(msg_id, None)
                    break  # Send to only one connection
                except (anyio.ClosedResourceError, anyio.EndOfStream):
                    self._connections.pop(conn_id, None)
            
            if success:
                return True
        
        logger.warning(f"No connection found for response to request {msg_id}")
        return False