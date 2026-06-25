"""A predictable event store for resumability tests.

The SDK's `EventStore` interface lets a streamable-HTTP server stamp every SSE event with an ID
and replay missed events when a client reconnects with `Last-Event-ID`. This implementation
issues sequential integer IDs starting at "1" so tests can assert exact IDs (the example store
uses uuid4, which cannot be snapshotted) and is small enough that every line is exercised by the
resumability tests themselves.
"""

import anyio
from mcp_types import JSONRPCMessage

from mcp.server.streamable_http import EventCallback, EventId, EventMessage, EventStore, StreamId


class SequencedEventStore(EventStore):
    """Stores every event in order and replays the same-stream tail after a given ID."""

    def __init__(self) -> None:
        self._events: list[tuple[StreamId, JSONRPCMessage | None]] = []
        self._milestones: dict[int, anyio.Event] = {}

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        self._events.append((stream_id, message))
        count = len(self._events)
        milestone = self._milestones.pop(count, None)
        if milestone is not None:
            milestone.set()
        return str(count)

    async def wait_until_stored(self, count: int) -> None:
        """Block until at least `count` events have been stored.

        Tests use this to wait for the server's message router (which runs in another task) to
        finish storing a known set of events before issuing a replay, so the replay's content is
        deterministic rather than depending on task scheduling order.
        """
        if len(self._events) >= count:
            return
        milestone = self._milestones.setdefault(count, anyio.Event())
        await milestone.wait()

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
