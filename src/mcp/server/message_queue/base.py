import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Protocol, runtime_checkable
from uuid import UUID

import mcp.types as types

logger = logging.getLogger(__name__)

MessageCallback = Callable[[types.JSONRPCMessage | Exception], Awaitable[None]]


@runtime_checkable
class MessageQueue(Protocol):
    """Abstract interface for SSE messaging.

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
    async def active_for_request(self, session_id: UUID, callback: MessageCallback):
        """Request-scoped context manager that ensures the listener is active.

        Args:
            session_id: The UUID of the session to activate
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


class InMemoryMessageQueue:
    """Default in-memory implementation of the MessageQueue interface.

    This implementation immediately calls registered callbacks when messages
    are received.
    """

    def __init__(self) -> None:
        self._callbacks: dict[UUID, MessageCallback] = {}
        self._active_sessions: set[UUID] = set()

    async def publish_message(
        self, session_id: UUID, message: types.JSONRPCMessage | Exception
    ) -> bool:
        """Publish a message for the specified session."""
        if not await self.session_exists(session_id):
            logger.warning(f"Message received for unknown session {session_id}")
            return False

        # Call the callback directly if registered
        if session_id in self._callbacks:
            await self._callbacks[session_id](message)
            logger.debug(f"Called callback for session {session_id}")
        else:
            logger.warning(f"No callback registered for session {session_id}")

        return True

    @asynccontextmanager
    async def active_for_request(self, session_id: UUID, callback: MessageCallback):
        """Request-scoped context manager that ensures the listener is active."""
        self._active_sessions.add(session_id)
        self._callbacks[session_id] = callback
        logger.debug(f"Registered session {session_id} with callback")

        try:
            yield
        finally:
            self._active_sessions.discard(session_id)
            if session_id in self._callbacks:
                del self._callbacks[session_id]
            logger.debug(f"Unregistered session {session_id}")

    async def session_exists(self, session_id: UUID) -> bool:
        """Check if a session exists."""
        return session_id in self._active_sessions
