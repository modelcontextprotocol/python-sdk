"""Event storage interface for streamable-HTTP resumability.

`EventStore` and its supporting types are the contract a resumable
streamable-HTTP server plugs a store into (see `mcp.server.streamable_http`,
which re-exports every name here). They are defined in this transport-agnostic
module - no web framework imported - so servers and application code can name
and type against them without loading the HTTP stack.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from mcp_types import JSONRPCMessage

__all__ = ["EventCallback", "EventId", "EventMessage", "EventStore", "StreamId"]

# Type aliases
StreamId = str
EventId = str


@dataclass
class EventMessage:
    """A JSONRPCMessage with an optional event ID for stream resumability."""

    message: JSONRPCMessage
    event_id: str | None = None


EventCallback = Callable[[EventMessage], Awaitable[None]]


class EventStore(ABC):
    """Interface for resumability support via event storage."""

    @abstractmethod
    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        """Stores an event for later retrieval.

        Args:
            stream_id: ID of the stream the event belongs to
            message: The JSON-RPC message to store, or None for priming events

        Returns:
            The generated event ID for the stored event.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        """Replays events that occurred after the specified event ID.

        Args:
            last_event_id: The ID of the last event the client received
            send_callback: A callback function to send events to the client

        Returns:
            The stream ID of the replayed events, or None if no events were found.
        """
        pass  # pragma: no cover
