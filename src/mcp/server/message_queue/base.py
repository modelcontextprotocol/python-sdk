"""
Base Message Queue Protocol and In-Memory Implementation

This module defines the message queue protocol and provides a default in-memory implementation.
"""

import logging
from typing import Protocol, runtime_checkable
from uuid import UUID

import mcp.types as types

logger = logging.getLogger(__name__)


@runtime_checkable
class MessageQueue(Protocol):
    """Abstract interface for an SSE message queue.
    
    This interface allows messages to be queued and processed by any SSE server instance,
    enabling multiple servers to handle requests for the same session.
    """
    
    async def add_message(self, session_id: UUID, message: types.JSONRPCMessage | Exception) -> bool:
        """Add a message to the queue for the specified session.
        
        Args:
            session_id: The UUID of the session this message is for
            message: The message to queue
            
        Returns:
            bool: True if message was accepted, False if session not found
        """
        ...
    
    async def get_message(self, session_id: UUID, timeout: float = 0.1) -> types.JSONRPCMessage | Exception | None:
        """Get the next message for the specified session.
        
        Args:
            session_id: The UUID of the session to get messages for
            timeout: Maximum time to wait for a message, in seconds
            
        Returns:
            The next message or None if no message is available
        """
        ...
    
    async def register_session(self, session_id: UUID) -> None:
        """Register a new session with the queue.
        
        Args:
            session_id: The UUID of the new session to register
        """
        ...
    
    async def unregister_session(self, session_id: UUID) -> None:
        """Unregister a session when it's closed.
        
        Args:
            session_id: The UUID of the session to unregister
        """
        ...
        
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
    
    This implementation keeps messages in memory for each session until they're retrieved.
    """
    
    def __init__(self) -> None:
        self._message_queues: dict[UUID, list[types.JSONRPCMessage | Exception]] = {}
        self._active_sessions: set[UUID] = set()
    
    async def add_message(self, session_id: UUID, message: types.JSONRPCMessage | Exception) -> bool:
        """Add a message to the queue for the specified session."""
        if session_id not in self._active_sessions:
            logger.warning(f"Message received for unknown session {session_id}")
            return False
            
        if session_id not in self._message_queues:
            self._message_queues[session_id] = []
        
        self._message_queues[session_id].append(message)
        logger.debug(f"Added message to queue for session {session_id}")
        return True
    
    async def get_message(self, session_id: UUID, timeout: float = 0.1) -> types.JSONRPCMessage | Exception | None:
        """Get the next message for the specified session."""
        if session_id not in self._active_sessions:
            return None
            
        queue = self._message_queues.get(session_id, [])
        if not queue:
            return None
            
        message = queue.pop(0)
        if not queue:  # Clean up empty queue
            del self._message_queues[session_id]
            
        return message
    
    async def register_session(self, session_id: UUID) -> None:
        """Register a new session with the queue."""
        self._active_sessions.add(session_id)
        logger.debug(f"Registered session {session_id}")
    
    async def unregister_session(self, session_id: UUID) -> None:
        """Unregister a session when it's closed."""
        self._active_sessions.discard(session_id)
        if session_id in self._message_queues:
            del self._message_queues[session_id]
        logger.debug(f"Unregistered session {session_id}")
        
    async def session_exists(self, session_id: UUID) -> bool:
        """Check if a session exists."""
        return session_id in self._active_sessions