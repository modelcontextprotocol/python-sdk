import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import ValidationError

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
        self, session_id: UUID, message: types.JSONRPCMessage | str
    ) -> bool:
        """Publish a message for the specified session.

        Args:
            session_id: The UUID of the session this message is for
            message: The message to publish (JSONRPCMessage or str for invalid JSON)

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

    async def close(self) -> None:
        """Close the message dispatch."""
        ...


class InMemoryMessageDispatch:
    """Default in-memory implementation of the MessageDispatch interface.

    This implementation immediately dispatches messages to registered callbacks when
    messages are received without any queuing behavior.
    """

    def __init__(self) -> None:
        self._callbacks: dict[UUID, MessageCallback] = {}

    async def publish_message(
        self, session_id: UUID, message: types.JSONRPCMessage | str
    ) -> bool:
        """Publish a message for the specified session."""
        if session_id not in self._callbacks:
            logger.warning(f"Message dropped: unknown session {session_id}")
            return False

        # Parse string messages or recreate original ValidationError
        if isinstance(message, str):
            try:
                callback_argument = types.JSONRPCMessage.model_validate_json(message)
            except ValidationError as exc:
                callback_argument = exc
        else:
            callback_argument = message

        # Call the callback with either valid message or recreated ValidationError
        await self._callbacks[session_id](callback_argument)

        logger.debug(f"Message dispatched to session {session_id}")
        return True

    @asynccontextmanager
    async def subscribe(self, session_id: UUID, callback: MessageCallback):
        """Request-scoped context manager that subscribes to messages for a session."""
        self._callbacks[session_id] = callback
        logger.debug(f"Subscribing to messages for session {session_id}")

        try:
            yield
        finally:
            if session_id in self._callbacks:
                del self._callbacks[session_id]
            logger.debug(f"Unsubscribed from session {session_id}")

    async def session_exists(self, session_id: UUID) -> bool:
        """Check if a session exists."""
        return session_id in self._callbacks

    async def close(self) -> None:
        """Close the message dispatch."""
        pass