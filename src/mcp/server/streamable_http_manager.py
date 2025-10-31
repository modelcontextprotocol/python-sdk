"""StreamableHTTP Session Manager for MCP servers."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from http import HTTPStatus
from typing import Any
from uuid import uuid4

import anyio
from anyio.abc import TaskStatus
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from mcp.server.lowlevel.server import Server as MCPServer
from mcp.server.streamable_http import (
    MCP_SESSION_ID_HEADER,
    EventStore,
    StreamableHTTPServerTransport,
)
from mcp.server.transport_security import TransportSecuritySettings

logger = logging.getLogger(__name__)


class StreamableHTTPSessionManager:
    """
    Manages StreamableHTTP sessions with optional resumability via event store.

    This class abstracts away the complexity of session management, event storage,
    and request handling for StreamableHTTP transports. It handles:

    1. Session tracking for clients
    2. Resumability via an optional event store
    3. Session roaming across multiple server instances
    4. Connection management and lifecycle
    5. Request handling and transport setup

    Important: Only one StreamableHTTPSessionManager instance should be created
    per application. The instance cannot be reused after its run() context has
    completed. If you need to restart the manager, create a new instance.

    Args:
        app: The MCP server instance
        event_store: Optional event store for resumability and session roaming.
                     If provided, enables:
                     - Event replay when clients reconnect (resumability)
                     - Session roaming across multiple server instances
                     When a client reconnects with a session ID not found in this
                     instance's memory, the presence of EventStore allows creating
                     a transport for that session (since events prove it existed).
                     This enables distributed deployments without sticky sessions.
                     If None, sessions are tracked locally but require sticky sessions
                     in multi-instance deployments.
        json_response: Whether to use JSON responses instead of SSE streams
        stateless: If True, creates a completely fresh transport for each request
                   with no session tracking or state persistence between requests.
    """

    def __init__(
        self,
        app: MCPServer[Any, Any],
        event_store: EventStore | None = None,
        json_response: bool = False,
        stateless: bool = False,
        security_settings: TransportSecuritySettings | None = None,
    ):
        self.app = app
        self.event_store = event_store
        self.json_response = json_response
        self.stateless = stateless
        self.security_settings = security_settings

        # Session tracking (only used if not stateless)
        self._session_creation_lock = anyio.Lock()
        self._server_instances: dict[str, StreamableHTTPServerTransport] = {}

        # The task group will be set during lifespan
        self._task_group = None
        # Thread-safe tracking of run() calls
        self._run_lock = anyio.Lock()
        self._has_started = False

    @contextlib.asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """
        Run the session manager with proper lifecycle management.

        This creates and manages the task group for all session operations.

        Important: This method can only be called once per instance. The same
        StreamableHTTPSessionManager instance cannot be reused after this
        context manager exits. Create a new instance if you need to restart.

        Use this in the lifespan context manager of your Starlette app:

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette) -> AsyncIterator[None]:
            async with session_manager.run():
                yield
        """
        # Thread-safe check to ensure run() is only called once
        async with self._run_lock:
            if self._has_started:
                raise RuntimeError(
                    "StreamableHTTPSessionManager .run() can only be called "
                    "once per instance. Create a new instance if you need to run again."
                )
            self._has_started = True

        async with anyio.create_task_group() as tg:
            # Store the task group for later use
            self._task_group = tg
            logger.info("StreamableHTTP session manager started")
            try:
                yield  # Let the application run
            finally:
                logger.info("StreamableHTTP session manager shutting down")
                # Cancel task group to stop all spawned tasks
                tg.cancel_scope.cancel()
                self._task_group = None
                # Clear any remaining server instances
                self._server_instances.clear()

    async def handle_request(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """
        Process ASGI request with proper session handling and transport setup.

        Dispatches to the appropriate handler based on stateless mode.

        Args:
            scope: ASGI scope
            receive: ASGI receive function
            send: ASGI send function
        """
        if self._task_group is None:
            raise RuntimeError("Task group is not initialized. Make sure to use run().")

        # Dispatch to the appropriate handler
        if self.stateless:
            await self._handle_stateless_request(scope, receive, send)
        else:
            await self._handle_stateful_request(scope, receive, send)

    async def _handle_stateless_request(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """
        Process request in stateless mode - creating a new transport for each request.

        Args:
            scope: ASGI scope
            receive: ASGI receive function
            send: ASGI send function
        """
        logger.debug("Stateless mode: Creating new transport for this request")
        # No session ID needed in stateless mode
        http_transport = StreamableHTTPServerTransport(
            mcp_session_id=None,  # No session tracking in stateless mode
            is_json_response_enabled=self.json_response,
            event_store=None,  # No event store in stateless mode
            security_settings=self.security_settings,
        )

        # Start server in a new task
        async def run_stateless_server(*, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED):
            async with http_transport.connect() as streams:
                read_stream, write_stream = streams
                task_status.started()
                try:
                    await self.app.run(
                        read_stream,
                        write_stream,
                        self.app.create_initialization_options(),
                        stateless=True,
                    )
                except Exception:
                    logger.exception("Stateless session crashed")

        # Assert task group is not None for type checking
        assert self._task_group is not None
        # Start the server task
        await self._task_group.start(run_stateless_server)

        # Handle the HTTP request and return the response
        await http_transport.handle_request(scope, receive, send)

        # Terminate the transport after the request is handled
        await http_transport.terminate()

    async def _handle_stateful_request(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """
        Process request in stateful mode - maintaining session state between requests.

        Args:
            scope: ASGI scope
            receive: ASGI receive function
            send: ASGI send function
        """
        request = Request(scope, receive)
        request_mcp_session_id = request.headers.get(MCP_SESSION_ID_HEADER)

        # Existing session case - check internal memory first
        if request_mcp_session_id is not None and request_mcp_session_id in self._server_instances:
            transport = self._server_instances[request_mcp_session_id]
            logger.debug("Session already exists, handling request directly")

            await transport.handle_request(scope, receive, send)
            return

        # Session roaming - EventStore proves session existed
        if request_mcp_session_id is not None and self.event_store is not None:
            logger.info(f"Session {request_mcp_session_id} roaming to this instance (EventStore enables roaming)")

            async with self._session_creation_lock:
                # Double-check it wasn't created while we waited for the lock
                if request_mcp_session_id not in self._server_instances:
                    http_transport = StreamableHTTPServerTransport(
                        mcp_session_id=request_mcp_session_id,  # Use provided session ID
                        is_json_response_enabled=self.json_response,
                        event_store=self.event_store,  # EventStore will replay events
                        security_settings=self.security_settings,
                    )

                    self._server_instances[request_mcp_session_id] = http_transport
                    logger.info(f"Created transport for roaming session: {request_mcp_session_id}")

                    await self._start_transport_server(http_transport)
                    transport = http_transport  # Use local reference to avoid race condition
                else:
                    # Another request created it while we waited for the lock
                    transport = self._server_instances[request_mcp_session_id]

            # Use the local transport reference (safe even if cleaned up from dict)
            await transport.handle_request(scope, receive, send)
            return

        if request_mcp_session_id is None:
            # New session case
            logger.debug("Creating new transport")
            async with self._session_creation_lock:
                new_session_id = uuid4().hex
                http_transport = StreamableHTTPServerTransport(
                    mcp_session_id=new_session_id,
                    is_json_response_enabled=self.json_response,
                    event_store=self.event_store,  # May be None (no resumability)
                    security_settings=self.security_settings,
                )

                assert http_transport.mcp_session_id is not None
                self._server_instances[http_transport.mcp_session_id] = http_transport
                logger.info(f"Created new transport with session ID: {new_session_id}")

                # Start the background server task
                await self._start_transport_server(http_transport)

                # Handle the HTTP request and return the response
                await http_transport.handle_request(scope, receive, send)
        else:
            # Invalid session ID
            response = Response(
                "Bad Request: No valid session ID provided",
                status_code=HTTPStatus.BAD_REQUEST,
            )
            await response(scope, receive, send)

    async def _transport_server_task(
        self,
        http_transport: StreamableHTTPServerTransport,
        *,
        task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        """
        Background task that runs the MCP server for a transport.

        This task:
        1. Connects the transport streams
        2. Runs the MCP server with those streams
        3. Handles errors and cleanup on server crash

        Args:
            http_transport: The transport to run the server for
            task_status: anyio task status for coordination with task group
        """
        async with http_transport.connect() as streams:
            read_stream, write_stream = streams
            task_status.started()
            try:
                await self.app.run(
                    read_stream,
                    write_stream,
                    self.app.create_initialization_options(),
                    stateless=False,  # Stateful mode
                )
            except Exception:
                logger.exception(f"Session {http_transport.mcp_session_id} crashed")
            finally:
                # Only remove from instances if not terminated
                if (
                    http_transport.mcp_session_id
                    and http_transport.mcp_session_id in self._server_instances
                    and not http_transport.is_terminated
                ):
                    logger.info(f"Cleaning up crashed session {http_transport.mcp_session_id} from active instances.")
                    del self._server_instances[http_transport.mcp_session_id]

    async def _start_transport_server(self, http_transport: StreamableHTTPServerTransport) -> None:
        """
        Start a background task to run the MCP server for this transport.

        Args:
            http_transport: The transport to start the server for
        """
        assert self._task_group is not None
        await self._task_group.start(self._transport_server_task, http_transport)
