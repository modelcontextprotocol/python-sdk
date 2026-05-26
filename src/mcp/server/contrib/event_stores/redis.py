"""Redis-backed EventStore for MCP SSE stream resumability.

Requires the redis extra:
    pip install "mcp[redis]"

Quickstart:
    import redis.asyncio as aioredis
    from mcp.server.contrib.event_stores import RedisEventStore
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    redis_client = aioredis.from_url("redis://localhost:6379")
    store = RedisEventStore(redis_client, ttl=3600)

    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=store,
    )
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.streamable_http import (
    EventCallback,
    EventId,
    EventMessage,
    EventStore,
    StreamId,
)
from mcp.types import JSONRPCMessage, jsonrpc_message_adapter

logger = logging.getLogger(__name__)


class RedisEventStore(EventStore):
    """EventStore backed by Redis for production multi-process deployments.

    Redis data layout:
        {prefix}counter                — STRING, atomic INCR source for EventIds
        {prefix}event:{event_id}       — HASH, fields: stream_id + payload
        {prefix}stream:{stream_id}     — ZSET, members: event_ids, scores: int(event_id)

    Args:
        redis:      An already-connected redis.asyncio.Redis instance.
        key_prefix: Prefix for all Redis keys. Use different prefixes when
                    multiple MCP servers share one Redis instance.
                    Default: "mcp:".
        ttl:        Seconds after which keys expire automatically.
                    None means keys never expire — strongly discouraged in
                    production. Recommended: at least 2× session_idle_timeout.
    """

    def __init__(
        self,
        redis: Any,  # redis.asyncio.Redis at runtime
        *,
        key_prefix: str = "mcp:",
        ttl: int | None = None,
    ) -> None:
        self._redis = redis
        self._prefix = key_prefix
        self._ttl = ttl

        if ttl is None:
            logger.warning(
                "RedisEventStore created with ttl=None. "
                "Events will accumulate indefinitely in Redis. "
                "Set ttl= to a positive number of seconds "
                "(recommended: at least 2× your session_idle_timeout)."
            )

    # Key helpers

    def _counter_key(self) -> str:
        return f"{self._prefix}counter"

    def _event_key(self, event_id: EventId) -> str:
        return f"{self._prefix}event:{event_id}"

    def _stream_key(self, stream_id: StreamId) -> str:
        return f"{self._prefix}stream:{stream_id}"

    # EventStore interface

    async def store_event(
        self,
        stream_id: StreamId,
        message: JSONRPCMessage | None,
    ) -> EventId:
        """Store an event and return its unique, monotonically increasing ID."""
        # Atomic increment — safe under concurrent writes from multiple workers
        event_id_int: int = await self._redis.incr(self._counter_key())
        event_id: EventId = str(event_id_int)

        # Serialise — empty string is the sentinel for priming events (no payload)
        if message is None:
            payload = ""
        else:
            payload = jsonrpc_message_adapter.dump_json(
                message,
                by_alias=True,
                exclude_none=True,
            ).decode("utf-8")

        # Store event metadata: which stream it belongs to + its payload
        await self._redis.hset(
            self._event_key(event_id),
            mapping={
                "stream_id": stream_id,
                "payload": payload,
            },
        )

        # Register in the stream's sorted set — score = int(event_id) for range queries
        await self._redis.zadd(
            self._stream_key(stream_id),
            {event_id: event_id_int},
        )

        # Refresh TTL on all touched keys (if configured)
        if self._ttl is not None:
            await self._redis.expire(self._event_key(event_id), self._ttl)
            await self._redis.expire(self._stream_key(stream_id), self._ttl)
            await self._redis.expire(self._counter_key(), self._ttl)

        return event_id

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        """Replay all events on the same stream that occurred after last_event_id."""
        # Look up which stream owns this event ID
        stream_id_raw: bytes | None = await self._redis.hget(self._event_key(last_event_id), "stream_id")

        if stream_id_raw is None:
            # Unknown or expired event ID — return None, don't raise
            return None

        stream_id: StreamId = stream_id_raw.decode("utf-8")

        # Fetch all event IDs in this stream with id strictly greater than last_event_id
        last_int = int(last_event_id)
        raw_ids: list[bytes] = await self._redis.zrangebyscore(
            self._stream_key(stream_id),
            min=last_int + 1,
            max="+inf",
        )

        for eid_bytes in raw_ids:
            eid: EventId = eid_bytes.decode("utf-8")

            payload_raw: bytes | None = await self._redis.hget(self._event_key(eid), "payload")

            if payload_raw is None:
                # Key expired between ZRANGEBYSCORE and HGET — skip silently
                logger.debug("Event %s payload missing during replay (expired?)", eid)
                continue

            payload_str = payload_raw.decode("utf-8")

            if not payload_str:
                # Empty string = priming event — never sent to clients
                continue

            message = jsonrpc_message_adapter.validate_json(payload_str)
            await send_callback(EventMessage(message=message, event_id=eid))

        return stream_id
