"""StreamableHTTP Session Manager for MCP servers."""

from __future__ import annotations

import contextlib
import logging
import time
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
    3. Connection management and lifecycle
    4. Request handling and transport setup

    Important: Only one StreamableHTTPSessionManager instance should be created
    per application. The instance cannot be reused after its run() context has
    completed. If you need to restart the manager, create a new instance.

    Args:
        app: The MCP server instance
        event_store: Optional event store for resumability support.
                     If provided, enables resumable connections where clients
                     can reconnect and receive missed events.
                     If None, sessions are still tracked but not resumable.
        json_response: Whether to use JSON responses instead of SSE streams
        stateless: If True, creates a completely fresh transport for each request
                   with no session tracking or state persistence between requests.
        security_settings: Optional security settings for DNS rebinding protection
        session_idle_timeout: Maximum idle time in seconds before a session is eligible
                             for cleanup. Default is 1800 seconds (30 minutes).
        cleanup_check_interval: Interval in seconds between cleanup checks.
                               Default is 300 seconds (5 minutes).
        max_sessions_before_cleanup: Threshold number of sessions before idle cleanup
                                    is activated. Default is 10000. Cleanup only runs
                                    when the session count exceeds this threshold.
    """

    def __init__(
        self,
        app: MCPServer[Any, Any],
        event_store: EventStore | None = None,
        json_response: bool = False,
        stateless: bool = False,
        security_settings: TransportSecuritySettings | None = None,
        session_idle_timeout: float = 1800,  # 30 minutes default
        cleanup_check_interval: float = 300,  # 5 minutes default
        max_sessions_before_cleanup: int = 10000,  # Threshold to activate cleanup
    ):
        self.app = app
        self.event_store = event_store
        self.json_response = json_response
        self.stateless = stateless
        self.security_settings = security_settings
        self.session_idle_timeout = session_idle_timeout
        self.cleanup_check_interval = cleanup_check_interval
        self.max_sessions_before_cleanup = max_sessions_before_cleanup

        # Session tracking (only used if not stateless)
        self._session_creation_lock = anyio.Lock()
        self._server_instances: dict[str, StreamableHTTPServerTransport] = {}
        self._session_last_activity: dict[str, float] = {}

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

            # Start the cleanup task if not in stateless mode
            if not self.stateless:
                tg.start_soon(self._run_session_cleanup)

            try:
                yield  # Let the application run
            finally:
                logger.info("StreamableHTTP session manager shutting down")
                # Cancel task group to stop all spawned tasks (this will also stop cleanup task)
                tg.cancel_scope.cancel()
                self._task_group = None
                # Clear any remaining server instances and tracking
                self._server_instances.clear()
                self._session_last_activity.clear()

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

        # Existing session case
        if request_mcp_session_id is not None and request_mcp_session_id in self._server_instances:
            transport = self._server_instances[request_mcp_session_id]
            logger.debug("Session already exists, handling request directly")
            # Update last activity time for this session
            if request_mcp_session_id:
                self._session_last_activity[request_mcp_session_id] = time.time()
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
                # Track initial activity time for new session
                self._session_last_activity[http_transport.mcp_session_id] = time.time()
                logger.info(f"Created new transport with session ID: {new_session_id}")

                # Define the server runner
                async def run_server(*, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
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
                        except Exception as e:
                            logger.error(
                                f"Session {http_transport.mcp_session_id} crashed: {e}",
                                exc_info=True,
                            )
                        finally:
                            # Only remove from instances if not terminated
                            if (
                                http_transport.mcp_session_id
                                and http_transport.mcp_session_id in self._server_instances
                                and not http_transport.is_terminated
                            ):
                                logger.info(
                                    "Cleaning up crashed session "
                                    f"{http_transport.mcp_session_id} from "
                                    "active instances."
                                )
                                del self._server_instances[http_transport.mcp_session_id]
                                # Also remove from activity tracking
                                self._session_last_activity.pop(http_transport.mcp_session_id, None)

                # Assert task group is not None for type checking
                assert self._task_group is not None
                # Start the server task
                await self._task_group.start(run_server)

                # Handle the HTTP request and return the response
                await http_transport.handle_request(scope, receive, send)
        else:
            # Invalid session ID
            response = Response(
                "Bad Request: No valid session ID provided",
                status_code=HTTPStatus.BAD_REQUEST,
            )
            await response(scope, receive, send)

    async def _run_session_cleanup(self) -> None:
        """
        Background task that periodically cleans up idle sessions.
        Only performs cleanup when the number of sessions exceeds the threshold.
        """
        logger.info(
            f"Session cleanup task started (threshold: {self.max_sessions_before_cleanup} sessions, "
            f"idle timeout: {self.session_idle_timeout}s)"
        )
        try:
            while True:
                await anyio.sleep(self.cleanup_check_interval)

                # Only perform cleanup if we're above the threshold
                session_count = len(self._server_instances)
                if session_count <= self.max_sessions_before_cleanup:
                    logger.debug(
                        f"Session count ({session_count}) below threshold "
                        f"({self.max_sessions_before_cleanup}), skipping cleanup"
                    )
                    continue

                logger.info(f"Session count ({session_count}) exceeds threshold, performing idle session cleanup")

                current_time = time.time()
                sessions_to_cleanup: list[tuple[str, float]] = []

                # Identify sessions that have been idle too long
                for session_id, last_activity in list(self._session_last_activity.items()):
                    idle_time = current_time - last_activity
                    if idle_time > self.session_idle_timeout:
                        sessions_to_cleanup.append((session_id, idle_time))

                # Clean up identified sessions
                for session_id, idle_time in sessions_to_cleanup:
                    try:
                        if session_id in self._server_instances:                           
                            transport = self._server_instances[session_id]
                            logger.info(f"Cleaning up idle session {session_id}")
                            # Terminate the transport to properly close resources
                            await transport.terminate()
                            # Remove from tracking dictionaries
                            del self._server_instances[session_id]
                            self._session_last_activity.pop(session_id, None)
                    except Exception:
                        logger.exception(f"Error cleaning up session {session_id}")

                if sessions_to_cleanup:
                    logger.info(
                        f"Cleaned up {len(sessions_to_cleanup)} idle sessions, "
                        f"{len(self._server_instances)} sessions remaining"
                    )

        except anyio.get_cancelled_exc_class():
            logger.info("Session cleanup task cancelled")
            raise
        except Exception:
            logger.exception("Unexpected error in session cleanup task - cleanup task terminated")
            # Don't re-raise - let the task end gracefully without crashing the server
