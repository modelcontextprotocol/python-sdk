"""
Redis-based event store for production session roaming.

This implementation provides persistent event storage across multiple server instances,
enabling session roaming without sticky sessions.
"""

import json
import logging
import time
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import redis.asyncio as redis  # type: ignore[import-not-found]
else:
    try:
        import redis.asyncio as redis  # type: ignore[import-not-found]
    except ImportError:
        redis = None  # type: ignore[assignment]

from mcp.server.streamable_http import (
    EventCallback,
    EventId,
    EventMessage,
    EventStore,
    StreamId,
)
from mcp.types import JSONRPCMessage

logger = logging.getLogger(__name__)


class RedisEventStore(EventStore):
    """
    Redis-based implementation of the EventStore interface.

    Features:
    - Persistent storage (survives server restarts)
    - Shared across multiple instances (enables session roaming)
    - Fast access (Redis in-memory with persistence)
    - Production-ready (handles thousands of concurrent sessions)

    Storage structure:
    - events:{stream_id} → Sorted Set of (score=timestamp, value=json(event_id, message))
    - event:{event_id} → Hash {stream_id, message, timestamp}

    This allows:
    1. Fast lookup by event_id (for replay_events_after)
    2. Ordered retrieval of events per stream
    3. Efficient cleanup of old events
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        max_events_per_stream: int = 1000,
    ):
        """Initialize the Redis event store.

        Args:
            redis_url: Redis connection URL
            max_events_per_stream: Maximum events to keep per stream
        """
        self.redis_url = redis_url
        self.max_events_per_stream = max_events_per_stream
        self._redis: Any = None
        self._event_counter = 0

    async def _get_redis(self) -> Any:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = await redis.from_url(  # type: ignore[misc]
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis  # type: ignore[return-value]

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage) -> EventId:
        """
        Store an event in Redis.

        Storage:
        1. Add to sorted set: events:{stream_id}
        2. Store event details: event:{event_id}
        3. Trim old events if over max_events_per_stream

        Returns:
            EventId: Unique identifier for the stored event
        """
        client = await self._get_redis()

        # Generate unique event ID (timestamp-based for ordering)
        timestamp = time.time()
        self._event_counter += 1
        event_id = f"{int(timestamp * 1000000)}_{self._event_counter}"

        # Serialize message to JSON
        message_json = json.dumps(cast(Any, message))

        # Use pipeline for atomic operations
        async with client.pipeline(transaction=True) as pipe:  # type: ignore[attr-defined]
            # Store event details in hash
            await pipe.hset(  # type: ignore[misc]
                f"event:{event_id}",
                mapping={
                    "stream_id": stream_id,
                    "message": message_json,
                    "timestamp": str(timestamp),
                },
            )

            # Add to stream's sorted set (score = timestamp for ordering)
            await pipe.zadd(f"events:{stream_id}", {event_id: timestamp})  # type: ignore[arg-type]

            # Trim old events (keep only last N events)
            # Keep from highest score (most recent) down
            await pipe.zremrangebyrank(  # type: ignore[attr-defined]
                f"events:{stream_id}",
                0,
                -(self.max_events_per_stream + 1),
            )

            await pipe.execute()  # type: ignore[misc]

        logger.debug("Stored event %s for stream %s", event_id, stream_id)
        return event_id

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        """
        Replay events that occurred after the specified event ID.

        Process:
        1. Look up last_event_id to get stream_id and timestamp
        2. Get all events from that stream after the timestamp
        3. Send each event through the callback

        Returns:
            StreamId if events were found and replayed, None if event not found
        """
        client = await self._get_redis()

        # Get the last event's details
        event_data: dict[str, Any] = await client.hgetall(f"event:{last_event_id}")  # type: ignore[misc]
        if not event_data:
            logger.warning("Event %s not found in Redis", last_event_id)
            return None

        # Extract stream_id and timestamp with type narrowing
        stream_id_value: str | None = event_data.get("stream_id")
        timestamp_value: str | None = event_data.get("timestamp")

        if not stream_id_value or not timestamp_value:
            logger.warning("Invalid event data for event %s", last_event_id)
            return None

        stream_id = str(stream_id_value)
        last_timestamp = float(timestamp_value)

        # Get all events from this stream after the last timestamp
        # ZRANGEBYSCORE returns events in ascending order (oldest first)
        event_ids: list[str] = await client.zrangebyscore(  # type: ignore[attr-defined]
            f"events:{stream_id}",
            min=f"({last_timestamp}",  # Exclusive of last_timestamp
            max="+inf",
        )

        # Replay each event
        replay_count = 0
        for event_id_item in event_ids:
            # Get event details
            event_details: dict[str, Any] = await client.hgetall(f"event:{event_id_item}")  # type: ignore[misc]
            if event_details:
                message_value: str | None = event_details.get("message")
                if message_value:
                    message = cast(JSONRPCMessage, json.loads(str(message_value)))
                    await send_callback(EventMessage(message, str(event_id_item)))
                    replay_count += 1

        if replay_count > 0:
            logger.info(
                "Replayed %d events for stream %s after event %s",
                replay_count,
                stream_id,
                last_event_id,
            )
        else:
            logger.debug(
                "No events to replay for stream %s after event %s",
                stream_id,
                last_event_id,
            )

        return stream_id

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.aclose()  # type: ignore[attr-defined]
            self._redis = None
            logger.info("Disconnected from Redis")
