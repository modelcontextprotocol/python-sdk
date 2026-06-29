"""In-memory event store demonstrating resumability; examples/testing only, not production."""

import logging
from collections import deque
from dataclasses import dataclass
from uuid import uuid4

from mcp.server.streamable_http import EventCallback, EventId, EventMessage, EventStore, StreamId
from mcp_types import JSONRPCMessage

logger = logging.getLogger(__name__)


@dataclass
class EventEntry:
    event_id: EventId
    stream_id: StreamId
    message: JSONRPCMessage | None  # None for priming events


class InMemoryEventStore(EventStore):
    """In-memory EventStore keeping the last N events per stream; for examples/testing, not production."""

    def __init__(self, max_events_per_stream: int = 100):
        self.max_events_per_stream = max_events_per_stream
        self.streams: dict[StreamId, deque[EventEntry]] = {}
        self.event_index: dict[EventId, EventEntry] = {}

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        """Store an event with a generated event ID; a None message records a priming event."""
        event_id = str(uuid4())
        event_entry = EventEntry(event_id=event_id, stream_id=stream_id, message=message)

        if stream_id not in self.streams:
            self.streams[stream_id] = deque(maxlen=self.max_events_per_stream)

        # A full deque silently evicts its oldest event on append; mirror that in event_index
        if len(self.streams[stream_id]) == self.max_events_per_stream:
            oldest_event = self.streams[stream_id][0]
            self.event_index.pop(oldest_event.event_id, None)

        self.streams[stream_id].append(event_entry)
        self.event_index[event_id] = event_entry

        return event_id

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        """Replays events that occurred after the specified event ID."""
        if last_event_id not in self.event_index:
            logger.warning(f"Event ID {last_event_id} not found in store")
            return None

        last_event = self.event_index[last_event_id]
        stream_id = last_event.stream_id
        stream_events = self.streams.get(last_event.stream_id, deque())

        found_last = False
        for event in stream_events:
            if found_last:
                # Priming events (None message) are not replayed
                if event.message is not None:
                    await send_callback(EventMessage(event.message, event.event_id))
            elif event.event_id == last_event_id:
                found_last = True

        return stream_id
