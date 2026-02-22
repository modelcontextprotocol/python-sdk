"""Server lifespan manager for holding server-scoped context.

This module provides the infrastructure for managing server-level lifecycle
resources that should live for the entire server process (database pools,
ML models, shared caches) as opposed to session-level resources (user
authentication, per-client state).
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.lowlevel.server import Server

logger = logging.getLogger(__name__)

# Context variable to hold server lifespan context
# This is set once at server startup and accessed by all sessions
# NOTE: Uses "server_lifespan_context_var" to be consistent with "request_ctx" naming
server_lifespan_context_var: contextvars.ContextVar[Any] = contextvars.ContextVar("server_lifespan_context")


@asynccontextmanager
async def default_server_lifespan(_: Server) -> AsyncIterator[None]:
    """Default server lifespan that does nothing.

    This is used when no server_lifespan is provided.
    """
    yield


class ServerLifespanManager:
    """Manages server-level lifespan context.

    This class is responsible for:
    1. Running the server lifespan async context manager
    2. Storing the resulting context in a context variable
    3. Providing access to the context for all sessions

    The server lifespan runs ONCE when the server process starts,
    unlike session lifespan which runs per-client connection.

    Usage:
        @asynccontextmanager
        async def my_server_lifespan(server):
            db_pool = await create_db_pool()
            try:
                yield {"db": db_pool}
            finally:
                await db_pool.close()

        manager = ServerLifespanManager(server_lifespan=my_server_lifespan)
        async with manager.run(server_instance):
            # Server lifespan context is now available
            # via server_lifespan_context_var context variable
            ...
    """

    def __init__(
        self,
        server_lifespan: Callable[[Server[Any]], AbstractAsyncContextManager[Any]] | None = None,
    ) -> None:
        """Initialize the server lifespan manager.

        Args:
            server_lifespan: Async context manager function that takes
                a Server instance and yields the server lifespan context.
                If None, uses default_server_lifespan.
        """
        self._server_lifespan = server_lifespan or default_server_lifespan

    @asynccontextmanager
    async def run(self, server: Server) -> AsyncIterator[Any]:
        """Run the server lifespan and store context.

        This enters the server lifespan async context manager and stores
        the yielded context in the server_lifespan_context_var context variable,
        making it accessible to all handlers across all sessions.

        Args:
            server: The Server instance to pass to the lifespan function

        Yields:
            The server lifespan context
        """
        async with self._server_lifespan(server) as context:
            # Store in context variable so all sessions can access it
            token = server_lifespan_context_var.set(context)
            logger.debug("Server lifespan context initialized")
            try:
                yield context
            finally:
                # Clean up context variable
                server_lifespan_context_var.reset(token)
                logger.debug("Server lifespan context cleaned up")

    @classmethod
    def get_context(cls) -> Any:
        """Get the current server lifespan context.

        Returns:
            The server lifespan context for the current server process

        Raises:
            LookupError: If no server lifespan context has been set
        """
        try:
            return server_lifespan_context_var.get()
        except LookupError as e:
            raise LookupError(
                "Server lifespan context is not available. "
                "Ensure server_lifespan is configured and the server has started."
            ) from e
