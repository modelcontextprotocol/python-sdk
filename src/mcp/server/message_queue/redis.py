import json
import logging
from uuid import UUID

import mcp.types as types

try:
    import redis.asyncio as redis
except ImportError:
    raise ImportError(
        "Redis support requires the 'redis' package. "
        "Install it with: 'uv add redis' or 'uv add \"mcp[redis]\"'"
    )

logger = logging.getLogger(__name__)


class RedisMessageQueue:
    """Redis implementation of the MessageQueue interface.

    This implementation uses Redis lists to store messages for each session.
    Redis provides persistence and allows multiple servers to share the same queue.
    """

    def __init__(
        self, redis_url: str = "redis://localhost:6379/0", prefix: str = "mcp:queue:"
    ) -> None:
        """Initialize Redis message queue.

        Args:
            redis_url: Redis connection string
            prefix: Key prefix for Redis keys to avoid collisions
        """
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._prefix = prefix
        self._active_sessions_key = f"{prefix}active_sessions"
        logger.debug(f"Initialized Redis message queue with URL: {redis_url}")

    def _session_queue_key(self, session_id: UUID) -> str:
        """Get the Redis key for a session's message queue."""
        return f"{self._prefix}session:{session_id.hex}"

    async def add_message(
        self, session_id: UUID, message: types.JSONRPCMessage | Exception
    ) -> bool:
        """Add a message to the queue for the specified session."""
        # Check if session exists
        if not await self.session_exists(session_id):
            logger.warning(f"Message received for unknown session {session_id}")
            return False

        # Serialize the message
        if isinstance(message, Exception):
            # For exceptions, store them as special format
            data = json.dumps(
                {
                    "_exception": True,
                    "type": type(message).__name__,
                    "message": str(message),
                }
            )
        else:
            data = message.model_dump_json(by_alias=True, exclude_none=True)

        # Push to the right side of the list (queue)
        await self._redis.rpush(self._session_queue_key(session_id), data)
        logger.debug(f"Added message to Redis queue for session {session_id}")
        return True

    async def get_message(
        self, session_id: UUID, timeout: float = 0.1
    ) -> types.JSONRPCMessage | Exception | None:
        """Get the next message for the specified session."""
        # Check if session exists
        if not await self.session_exists(session_id):
            return None

        # Pop from the left side of the list (queue)
        # Use BLPOP with timeout to avoid busy waiting
        result = await self._redis.blpop([self._session_queue_key(session_id)], timeout)

        if not result:
            return None

        # result is a tuple of (key, value)
        _, data = result

        # Deserialize the message
        json_data = json.loads(data)

        # Check if it's an exception
        if isinstance(json_data, dict) and json_data.get("_exception"):
            # Reconstitute a generic exception
            return Exception(f"{json_data['type']}: {json_data['message']}")

        # Regular message
        try:
            return types.JSONRPCMessage.model_validate_json(data)
        except Exception as e:
            logger.error(f"Failed to deserialize message: {e}")
            return None

    async def register_session(self, session_id: UUID) -> None:
        """Register a new session with the queue."""
        # Add session ID to the set of active sessions
        await self._redis.sadd(self._active_sessions_key, session_id.hex)
        logger.debug(f"Registered session {session_id} in Redis")

    async def unregister_session(self, session_id: UUID) -> None:
        """Unregister a session when it's closed."""
        # Remove session ID from active sessions
        await self._redis.srem(self._active_sessions_key, session_id.hex)
        # Delete the session's message queue
        await self._redis.delete(self._session_queue_key(session_id))
        logger.debug(f"Unregistered session {session_id} from Redis")

    async def session_exists(self, session_id: UUID) -> bool:
        """Check if a session exists."""
        return bool(
            await self._redis.sismember(self._active_sessions_key, session_id.hex)
        )
