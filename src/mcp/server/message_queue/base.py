import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Protocol, runtime_checkable
from uuid import UUID

import mcp.types as types

logger = logging.getLogger(__name__)

MessageCallback = Callable[[types.JSONRPCMessage | Exception], Awaitable[None]]


@runtime_checkable
class MessageDispatch(Protocol):
    """Abstract interface for SSE message dispatching.

    This interface allows messages to be published to sessions and callbacks to be
    registered for message handling, enabling multiple servers to handle requests.
    """

    async def publish_message(
        self, session_id: UUID, message: types.JSONRPCMessage | Exception
    ) -> bool:
        """Publish a message for the specified session.

        Args:
            session_id: The UUID of the session this message is for
            message: The message to publish

        Returns:
            bool: True if message was published, False if session not found
        """
        ...

    @asynccontextmanager
    async def subscribe(self, session_id: UUID, callback: MessageCallback):
        """Request-scoped context manager that subscribes to messages for a session.

        Args:
            session_id: The UUID of the session to subscribe to
            callback: Async callback function to handle messages for this session
        """
        yield

    async def session_exists(self, session_id: UUID) -> bool:
        """Check if a session exists.

        Args:
            session_id: The UUID of the session to check

        Returns:
            bool: True if the session is active, False otherwise
        """
        ...


class InMemoryMessageDispatch:
    """Default in-memory implementation of the MessageDispatch interface.

    This implementation immediately dispatches messages to registered callbacks when 
    messages are received without any queuing behavior.
    """

    def __init__(self) -> None:
        self._callbacks: dict[UUID, MessageCallback] = {}
        # We don't need a separate _active_sessions set since _callbacks already tracks this

    async def publish_message(
        self, session_id: UUID, message: types.JSONRPCMessage | Exception
    ) -> bool:
        """Publish a message for the specified session."""
        if session_id not in self._callbacks:
            logger.warning(f"Message received for unknown session {session_id}")
            return False

        # Call the callback directly
        await self._callbacks[session_id](message)
        logger.debug(f"Called callback for session {session_id}")

        return True

    @asynccontextmanager
    async def subscribe(self, session_id: UUID, callback: MessageCallback):
        """Request-scoped context manager that subscribes to messages for a session."""
        self._callbacks[session_id] = callback
        logger.debug(f"Registered session {session_id} with callback")

        try:
            yield
        finally:
            if session_id in self._callbacks:
                del self._callbacks[session_id]
            logger.debug(f"Unregistered session {session_id}")

    async def session_exists(self, session_id: UUID) -> bool:
        """Check if a session exists."""
        return session_id in self._callbacks
