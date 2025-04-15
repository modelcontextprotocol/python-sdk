import logging
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID
from pydantic import ValidationError

import anyio
from anyio import CapacityLimiter, lowlevel

import mcp.types as types
from mcp.server.message_queue.base import MessageCallback

try:
    import redis.asyncio as redis
except ImportError:
    raise ImportError(
        "Redis support requires the 'redis' package. "
        "Install it with: 'uv add redis' or 'uv add \"mcp[redis]\"'"
    )

logger = logging.getLogger(__name__)


class RedisMessageDispatch:
    """Redis implementation of the MessageDispatch interface using pubsub.

    This implementation uses Redis pubsub for real-time message distribution across
    multiple servers handling the same sessions.
    """

    def __init__(
        self, redis_url: str = "redis://localhost:6379/0", prefix: str = "mcp:pubsub:"
    ) -> None:
        """Initialize Redis message dispatch.

        Args:
            redis_url: Redis connection string
            prefix: Key prefix for Redis channels to avoid collisions
        """
        self._redis = redis.from_url(redis_url, decode_responses=True)  # type: ignore
        self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)  # type: ignore
        self._prefix = prefix
        self._active_sessions_key = f"{prefix}active_sessions"
        self._callbacks: dict[UUID, MessageCallback] = {}
        # Ensures only one polling task runs at a time for message handling
        self._limiter = CapacityLimiter(1)
        logger.debug(f"Redis message dispatch initialized: {redis_url}")

    def _session_channel(self, session_id: UUID) -> str:
        """Get the Redis channel for a session."""
        return f"{self._prefix}session:{session_id.hex}"

    @asynccontextmanager
    async def subscribe(self, session_id: UUID, callback: MessageCallback):
        """Request-scoped context manager that subscribes to messages for a session."""
        await self._redis.sadd(self._active_sessions_key, session_id.hex)
        self._callbacks[session_id] = callback
        channel = self._session_channel(session_id)
        await self._pubsub.subscribe(channel)  # type: ignore

        logger.debug(f"Subscribing to Redis channel for session {session_id}")
        async with anyio.create_task_group() as tg:
            tg.start_soon(self._listen_for_messages)
            try:
                yield
            finally:
                tg.cancel_scope.cancel()
                await self._pubsub.unsubscribe(channel)  # type: ignore
                await self._redis.srem(self._active_sessions_key, session_id.hex)
                del self._callbacks[session_id]
                logger.debug(f"Unsubscribed from Redis channel for session {session_id}")

    async def _listen_for_messages(self) -> None:
        """Background task that listens for messages on subscribed channels."""
        async with self._limiter:
            while True:
                await lowlevel.checkpoint()
                message: None | dict[str, Any] = await self._pubsub.get_message(  # type: ignore
                    ignore_subscribe_messages=True,
                    timeout=None,  # type: ignore
                )
                if message is None:
                    continue

                channel: str = cast(str, message["channel"])
                expected_prefix = f"{self._prefix}session:"
                
                if not channel.startswith(expected_prefix):
                    logger.debug(f"Ignoring message from non-MCP channel: {channel}")
                    continue
                
                session_hex = channel[len(expected_prefix):]
                try:
                    session_id = UUID(hex=session_hex)
                    expected_channel = self._session_channel(session_id)
                    if channel != expected_channel:
                        logger.error(f"Channel format mismatch: {channel}")
                        continue
                except ValueError:
                    logger.error(f"Received message with invalid UUID in channel: {channel}")
                    continue

                data: str = cast(str, message["data"])
                try:
                    if session_id not in self._callbacks:
                        logger.warning(f"Message dropped: no callback for session {session_id}")
                        continue
                        
                    # Try to parse as valid message or recreate original ValidationError
                    try:
                        msg = types.JSONRPCMessage.model_validate_json(data)
                        await self._callbacks[session_id](msg)
                    except ValidationError as exc:
                        # Pass the identical validation error that would have occurred originally
                        await self._callbacks[session_id](exc)
                except Exception as e:
                    logger.error(f"Error processing message for session {session_id}: {e}")

    async def publish_message(
        self, session_id: UUID, message: types.JSONRPCMessage | str
    ) -> bool:
        """Publish a message for the specified session."""
        if not await self.session_exists(session_id):
            logger.warning(f"Message dropped: unknown session {session_id}")
            return False

        # Pass raw JSON strings directly, preserving validation errors
        if isinstance(message, str):
            data = message
        else:
            data = message.model_dump_json()

        channel = self._session_channel(session_id)
        await self._redis.publish(channel, data)  # type: ignore[attr-defined]
        logger.debug(f"Message published to Redis channel for session {session_id}")
        return True

    async def session_exists(self, session_id: UUID) -> bool:
        """Check if a session exists."""
        return bool(
            await self._redis.sismember(self._active_sessions_key, session_id.hex)  # type: ignore[attr-defined]
        )
