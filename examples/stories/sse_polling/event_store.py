"""Minimal in-memory `EventStore` for the SSE-resumability example.

Sequential integer IDs so the wire is readable; a production server would back
this interface with persistent storage so replay survives a process restart.
"""

from mcp.server.streamable_http import EventCallback, EventId, EventMessage, EventStore, StreamId
from mcp.types import JSONRPCMessage


class InMemoryEventStore(EventStore):
    """Stores every event in arrival order and replays the same-stream tail after a given ID."""

    def __init__(self) -> None:
        self._events: list[tuple[StreamId, JSONRPCMessage | None]] = []

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        self._events.append((stream_id, message))
        return str(len(self._events))

    async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
        try:
            cursor = int(last_event_id)
        except ValueError:
            return None
        if not 0 < cursor <= len(self._events):
            return None
        stream_id, _ = self._events[cursor - 1]
        for index in range(cursor, len(self._events)):
            event_stream_id, message = self._events[index]
            if event_stream_id == stream_id and message is not None:
                await send_callback(EventMessage(message, str(index + 1)))
        return stream_id
