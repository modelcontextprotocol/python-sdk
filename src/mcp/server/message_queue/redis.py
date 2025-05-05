import logging
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID

import anyio
from anyio import CancelScope, CapacityLimiter, lowlevel
from anyio.abc import TaskGroup
from pydantic import ValidationError

from mcp.server.message_queue.base import MessageCallback
from mcp.shared.message import SessionMessage

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
        self,
        redis_url: str = "redis://localhost:6379/0",
        prefix: str = "mcp:pubsub:",
        session_ttl: int = 3600,  # 1 hour default TTL for sessions
    ) -> None:
        """Initialize Redis message dispatch.

        Args:
            redis_url: Redis connection string
            prefix: Key prefix for Redis channels to avoid collisions
            session_ttl: TTL in seconds for session keys (default: 1 hour)
        """
        self._redis = redis.from_url(redis_url, decode_responses=True)  # type: ignore
        self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)  # type: ignore
        self._prefix = prefix
        self._session_ttl = session_ttl
        # Maps session IDs to the callback and task group for that SSE session.
        self._session_state: dict[UUID, tuple[MessageCallback, TaskGroup]] = {}
        # Ensures only one polling task runs at a time for message handling
        self._limiter = CapacityLimiter(1)
        logger.debug(f"Redis message dispatch initialized: {redis_url}")

    async def close(self):
        await self._pubsub.aclose()  # type: ignore
        await self._redis.aclose()  # type: ignore

    def _session_channel(self, session_id: UUID) -> str:
        """Get the Redis channel for a session."""
        return f"{self._prefix}session:{session_id.hex}"

    def _session_key(self, session_id: UUID) -> str:
        """Get the Redis key for a session."""
        return f"{self._prefix}session_active:{session_id.hex}"

    @asynccontextmanager
    async def subscribe(self, session_id: UUID, callback: MessageCallback):
        """Request-scoped context manager that subscribes to messages for a session."""
        session_key = self._session_key(session_id)
        await self._redis.setex(session_key, self._session_ttl, "1")  # type: ignore

        channel = self._session_channel(session_id)
        await self._pubsub.subscribe(channel)  # type: ignore

        logger.debug(f"Subscribing to Redis channel for session {session_id}")
        async with anyio.create_task_group() as tg:
            self._session_state[session_id] = (callback, tg)
            tg.start_soon(self._listen_for_messages)
            # Start heartbeat for this session
            tg.start_soon(self._session_heartbeat, session_id)
            try:
                yield
            finally:
                with anyio.CancelScope(shield=True):
                    tg.cancel_scope.cancel()
                    await self._pubsub.unsubscribe(channel)  # type: ignore
                    await self._redis.delete(session_key)  # type: ignore
                    del self._session_state[session_id]
                    logger.debug(f"Unsubscribed from Redis channel: {session_id}")

    async def _session_heartbeat(self, session_id: UUID) -> None:
        """Periodically refresh the TTL for a session."""
        session_key = self._session_key(session_id)
        while True:
            await lowlevel.checkpoint()
            try:
                # Refresh TTL at half the TTL interval to avoid expiration
                await anyio.sleep(self._session_ttl / 2)
                with anyio.CancelScope(shield=True):
                    await self._redis.expire(session_key, self._session_ttl)  # type: ignore
            except anyio.get_cancelled_exc_class():
                break
            except Exception as e:
                logger.error(f"Error refreshing TTL for session {session_id}: {e}")

    def _extract_session_id(self, channel: str) -> UUID | None:
        """Extract and validate session ID from channel."""
        expected_prefix = f"{self._prefix}session:"
        if not channel.startswith(expected_prefix):
            return None

        session_hex = channel[len(expected_prefix) :]
        try:
            session_id = UUID(hex=session_hex)
            if channel != self._session_channel(session_id):
                logger.error(f"Channel format mismatch: {channel}")
                return None
            return session_id
        except ValueError:
            logger.error(f"Invalid UUID in channel: {channel}")
            return None

    async def _listen_for_messages(self) -> None:
        """Background task that listens for messages on subscribed channels."""
        async with self._limiter:
            while True:
                await lowlevel.checkpoint()
                with CancelScope(shield=True):
                    message: None | dict[str, Any] = await self._pubsub.get_message(  # type: ignore
                        ignore_subscribe_messages=True,
                        timeout=0.1,  # type: ignore
                    )
                    if message is None:
                        continue

                    channel: str = cast(str, message["channel"])
                    session_id = self._extract_session_id(channel)
                    if session_id is None:
                        logger.debug(
                            f"Ignoring message from non-MCP channel: {channel}"
                        )
                        continue

                    data: str = cast(str, message["data"])
                    try:
                        if session_state := self._session_state.get(session_id):
                            session_state[1].start_soon(
                                self._handle_message, session_id, data
                            )
                        else:
                            logger.warning(
                                f"Message dropped: unknown session {session_id}"
                            )
                    except Exception as e:
                        logger.error(f"Error processing message for {session_id}: {e}")

    async def _handle_message(self, session_id: UUID, data: str) -> None:
        """Process a message from Redis in the session's task group."""
        if (session_state := self._session_state.get(session_id)) is None:
            logger.warning(f"Message dropped: callback removed for {session_id}")
            return

        try:
            # Parse message or pass validation error to callback
            msg_or_error = None
            try:
                msg_or_error = SessionMessage.model_validate_json(data)
            except ValidationError as exc:
                msg_or_error = exc

            await session_state[0](msg_or_error)
        except Exception as e:
            logger.error(f"Error in message handler for {session_id}: {e}")

    async def publish_message(
        self, session_id: UUID, message: SessionMessage | str
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
        session_key = self._session_key(session_id)
        return bool(await self._redis.exists(session_key))  # type: ignore
