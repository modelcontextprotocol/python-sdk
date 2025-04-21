import logging
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID, uuid4

import anyio
from anyio import CancelScope, CapacityLimiter, Event, lowlevel
from anyio.abc import TaskGroup

import mcp.types as types
from mcp.server.message_queue.base import MessageCallback, MessageWrapper

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
        self._limiter = CapacityLimiter(1)
        self._ack_events: dict[str, Event] = {}

        logger.debug(f"Redis message dispatch initialized: {redis_url}")

    def _session_channel(self, session_id: UUID) -> str:
        """Get the Redis channel for a session."""
        return f"{self._prefix}session:{session_id.hex}"

    def _ack_channel(self, session_id: UUID) -> str:
        """Get the acknowledgment channel for a session."""
        return f"{self._prefix}ack:{session_id.hex}"

    @asynccontextmanager
    async def subscribe(self, session_id: UUID, callback: MessageCallback):
        """Request-scoped context manager that subscribes to messages for a session."""
        await self._redis.sadd(self._active_sessions_key, session_id.hex)
        self._callbacks[session_id] = callback

        session_channel = self._session_channel(session_id)
        ack_channel = self._ack_channel(session_id)

        await self._pubsub.subscribe(session_channel)  # type: ignore
        await self._pubsub.subscribe(ack_channel)  # type: ignore

        logger.debug(f"Subscribing to Redis channels for session {session_id}")

        # Two nested task groups ensure proper cleanup: the inner one cancels the
        # listener, while the outer one allows any handlers to complete before exiting.
        async with anyio.create_task_group() as tg_handler:
            async with anyio.create_task_group() as tg:
                tg.start_soon(self._listen_for_messages, tg_handler)
                try:
                    yield
                finally:
                    tg.cancel_scope.cancel()
                    await self._pubsub.unsubscribe(session_channel)  # type: ignore
                    await self._pubsub.unsubscribe(ack_channel)  # type: ignore
                    await self._redis.srem(self._active_sessions_key, session_id.hex)
                    del self._callbacks[session_id]
                    logger.debug(
                        f"Unsubscribed from Redis channels for session {session_id}"
                    )

    async def _listen_for_messages(self, tg_handler: TaskGroup) -> None:
        """Background task that listens for messages on subscribed channels."""
        async with self._limiter:
            while True:
                await lowlevel.checkpoint()
                # Shield message retrieval from cancellation to ensure no messages are
                # lost when a session disconnects during processing.
                with CancelScope(shield=True):
                    redis_message: (  # type: ignore
                        None | dict[str, Any]
                    ) = await self._pubsub.get_message(  # type: ignore
                        ignore_subscribe_messages=True,
                        timeout=0.1,  # type: ignore
                    )
                    if redis_message is None:
                        continue

                    channel: str = cast(str, redis_message["channel"])
                    data: str = cast(str, redis_message["data"])

                    # Handle acknowledgment messages
                    if channel.startswith(f"{self._prefix}ack:"):
                        tg_handler.start_soon(self._handle_ack_message, channel, data)
                        continue

                    # Handle session messages
                    elif channel.startswith(f"{self._prefix}session:"):
                        tg_handler.start_soon(
                            self._handle_session_message, channel, data
                        )
                        continue

                    # Ignore other channels
                    else:
                        logger.debug(
                            f"Ignoring message from non-MCP channel: {channel}"
                        )

    async def _handle_ack_message(self, channel: str, data: str) -> None:
        """Handle acknowledgment messages received on ack channels."""
        ack_prefix = f"{self._prefix}ack:"
        if not channel.startswith(ack_prefix):
            return

        # Validate channel format exactly matches our expected format
        session_hex = channel[len(ack_prefix) :]
        try:
            # Validate this is a valid UUID hex and channel has correct format
            session_id = UUID(hex=session_hex)
            expected_channel = self._ack_channel(session_id)
            if channel != expected_channel:
                logger.error(
                    f"Channel mismatch: got {channel}, expected {expected_channel}"
                )
                return
        except ValueError:
            logger.error(f"Invalid UUID hex in ack channel: {channel}")
            return

        # Extract message ID from data
        message_id = data.strip()
        if message_id in self._ack_events:
            logger.debug(f"Received acknowledgment for message: {message_id}")
            self._ack_events[message_id].set()

    async def _handle_session_message(self, channel: str, data: str) -> None:
        """Handle regular messages received on session channels."""
        session_prefix = f"{self._prefix}session:"
        if not channel.startswith(session_prefix):
            return

        session_hex = channel[len(session_prefix) :]
        try:
            session_id = UUID(hex=session_hex)
            expected_channel = self._session_channel(session_id)
            if channel != expected_channel:
                logger.error(
                    f"Channel mismatch: got {channel}, expected {expected_channel}"
                )
                return
        except ValueError:
            logger.error(f"Invalid UUID hex in session channel: {channel}")
            return

        if session_id not in self._callbacks:
            logger.warning(f"Message dropped: no callback for {session_id}")
            return

        try:
            wrapper = MessageWrapper.model_validate_json(data)
            result = wrapper.get_json_rpc_message()
            await self._callbacks[session_id](result)
            await self._send_acknowledgment(session_id, wrapper.message_id)

        except Exception as e:
            logger.error(f"Error processing message for {session_id}: {e}")

    async def _send_acknowledgment(self, session_id: UUID, message_id: str) -> None:
        """Send an acknowledgment for a message that was successfully processed."""
        ack_channel = self._ack_channel(session_id)
        await self._redis.publish(ack_channel, message_id)  # type: ignore
        logger.debug(
            f"Sent acknowledgment for message {message_id} to session {session_id}"
        )

    async def publish_message(
        self,
        session_id: UUID,
        message: types.JSONRPCMessage | str,
        message_id: str | None = None,
    ) -> str | None:
        """Publish a message for the specified session."""
        if not await self.session_exists(session_id):
            logger.warning(f"Message dropped: unknown session {session_id}")
            return None

        # Pass raw JSON strings directly, preserving validation errors
        message_id = message_id or str(uuid4())
        if isinstance(message, str):
            wrapper = MessageWrapper(message_id=message_id, payload=message)
        else:
            wrapper = MessageWrapper(
                message_id=message_id, payload=message.model_dump_json()
            )

        channel = self._session_channel(session_id)
        await self._redis.publish(channel, wrapper.model_dump_json())  # type: ignore
        logger.debug(
            f"Message {message_id} published to Redis channel for session {session_id}"
        )
        return message_id

    async def publish_message_sync(
        self,
        session_id: UUID,
        message: types.JSONRPCMessage | str,
        timeout: float = 120.0,
    ) -> bool:
        """Publish a message and wait for acknowledgment of processing."""
        message_id = str(uuid4())
        ack_event = Event()
        self._ack_events[message_id] = ack_event

        try:
            published_id = await self.publish_message(session_id, message, message_id)
            if published_id is None:
                return False

            with anyio.fail_after(timeout):
                await ack_event.wait()
                logger.debug(f"Received acknowledgment for message {message_id}")
                return True

        except TimeoutError:
            logger.warning(
                f"Timed out waiting for acknowledgment of message {message_id}"
            )
            return False

        finally:
            if message_id in self._ack_events:
                del self._ack_events[message_id]

    async def session_exists(self, session_id: UUID) -> bool:
        """Check if a session exists."""
        return bool(
            await self._redis.sismember(self._active_sessions_key, session_id.hex)  # type: ignore[attr-defined]
        )
