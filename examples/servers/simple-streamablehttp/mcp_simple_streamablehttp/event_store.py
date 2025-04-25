"""
In-memory event store for demonstrating resumability functionality.

This is a simple implementation intended for examples and testing,
not for production use where a persistent storage solution would be more appropriate.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from operator import itemgetter
from uuid import uuid4

from mcp.server.streamable_http import EventId, EventStore, StreamId
from mcp.types import JSONRPCMessage

logger = logging.getLogger(__name__)


class InMemoryEventStore(EventStore):
    """
    Simple in-memory implementation of the EventStore interface for resumability.
    This is primarily intended for examples and testing, not for production use
    where a persistent storage solution would be more appropriate.
    """

    def __init__(self):
        self.events: dict[
            str, tuple[str, JSONRPCMessage, float]
        ] = {}  # event_id -> (stream_id, message, timestamp)

    async def store_event(
        self, stream_id: StreamId, message: JSONRPCMessage
    ) -> EventId:
        """Stores an event with a generated event ID."""
        event_id = str(uuid4())
        self.events[event_id] = (stream_id, message, time.time())
        return event_id

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: Callable[[EventId, JSONRPCMessage], Awaitable[None]],
    ) -> StreamId:
        """Replays events that occurred after the specified event ID."""
        logger.debug(f"Attempting to replay events after {last_event_id}")
        logger.debug(f"Total events in store: {len(self.events)}")
        logger.debug(f"Event IDs in store: {list(self.events.keys())}")

        if not last_event_id or last_event_id not in self.events:
            logger.warning(f"Event ID {last_event_id} not found in store")
            return ""

        # Get the stream ID and timestamp from the last event
        stream_id, _, last_timestamp = self.events[last_event_id]

        # Find all events for this stream after the last event
        events_sorted = sorted(
            [
                (event_id, message, timestamp)
                for event_id, (sid, message, timestamp) in self.events.items()
                if sid == stream_id and timestamp > last_timestamp
            ],
            key=itemgetter(2),
        )

        events_to_replay = [
            (event_id, message) for event_id, message, _ in events_sorted
        ]

        logger.debug(f"Found {len(events_to_replay)} events to replay")
        logger.debug(
            f"Events to replay: {[event_id for event_id, _ in events_to_replay]}"
        )

        # Send all events in order
        for event_id, message in events_to_replay:
            await send_callback(event_id, message)

        return stream_id
