import json
import logging
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID

import anyio
from anyio import CapacityLimiter

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


class RedisMessageQueue:
    """Redis implementation of the MessageQueue interface using pubsub.

    This implementation uses Redis pubsub for real-time message distribution across
    multiple servers handling the same sessions.
    """

    def __init__(
        self, redis_url: str = "redis://localhost:6379/0", prefix: str = "mcp:pubsub:"
    ) -> None:
        """Initialize Redis message queue.

        Args:
            redis_url: Redis connection string
            prefix: Key prefix for Redis channels to avoid collisions
        """
        self._redis = redis.from_url(redis_url, decode_responses=True)  # type: ignore
        self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)  # type: ignore
        self._prefix = prefix
        self._active_sessions_key = f"{prefix}active_sessions"
        self._callbacks: dict[UUID, MessageCallback] = {}
        self._limiter = CapacityLimiter(1)
        logger.debug(f"Initialized Redis message queue with URL: {redis_url}")

    def _session_channel(self, session_id: UUID) -> str:
        """Get the Redis channel for a session."""
        return f"{self._prefix}session:{session_id.hex}"

    @asynccontextmanager
    async def active_for_request(self, session_id: UUID, callback: MessageCallback):
        """Request-scoped context manager that ensures the listener task is running."""
        await self._redis.sadd(self._active_sessions_key, session_id.hex)
        self._callbacks[session_id] = callback
        channel = self._session_channel(session_id)
        await self._pubsub.subscribe(channel)  # type: ignore

        logger.debug(f"Registered session {session_id} in Redis with callback")
        async with anyio.create_task_group() as tg:
            tg.start_soon(self._listen_for_messages)
            try:
                yield
            finally:
                tg.cancel_scope.cancel()
                await self._pubsub.unsubscribe(channel)  # type: ignore
                await self._redis.srem(self._active_sessions_key, session_id.hex)
                del self._callbacks[session_id]
                logger.debug(f"Unregistered session {session_id} from Redis")

    async def _listen_for_messages(self) -> None:
        """Background task that listens for messages on subscribed channels."""
        async with self._limiter:
            while True:
                message: None | dict[str, Any] = await self._pubsub.get_message(  # type: ignore
                    ignore_subscribe_messages=True,
                    timeout=None,  # type: ignore
                )
                if message is None:
                    continue

                # Extract session ID from channel name
                channel: str = cast(str, message["channel"])
                if not channel.startswith(self._prefix):
                    continue

                session_hex = channel.split(":")[-1]
                try:
                    session_id = UUID(hex=session_hex)
                except ValueError:
                    logger.error(f"Invalid session channel: {channel}")
                    continue

                data: str = cast(str, message["data"])
                msg: None | types.JSONRPCMessage | Exception = None
                try:
                    json_data = json.loads(data)
                    if isinstance(json_data, dict):
                        json_dict: dict[str, Any] = json_data
                        if json_dict.get("_exception", False):
                            msg = Exception(
                                f"{json_dict['type']}: {json_dict['message']}"
                            )
                        else:
                            msg = types.JSONRPCMessage.model_validate_json(data)

                    if msg and session_id in self._callbacks:
                        await self._callbacks[session_id](msg)
                except Exception as e:
                    logger.error(f"Failed to process message: {e}")

    async def publish_message(
        self, session_id: UUID, message: types.JSONRPCMessage | Exception
    ) -> bool:
        """Publish a message for the specified session."""
        if not await self.session_exists(session_id):
            logger.warning(f"Message received for unknown session {session_id}")
            return False

        if isinstance(message, Exception):
            data = json.dumps(
                {
                    "_exception": True,
                    "type": type(message).__name__,
                    "message": str(message),
                }
            )
        else:
            data = message.model_dump_json()

        channel = self._session_channel(session_id)
        await self._redis.publish(channel, data)  # type: ignore[attr-defined]
        logger.debug(f"Published message to Redis channel for session {session_id}")
        return True

    async def session_exists(self, session_id: UUID) -> bool:
        """Check if a session exists."""
        return bool(
            await self._redis.sismember(self._active_sessions_key, session_id.hex)  # type: ignore[attr-defined]
        )
