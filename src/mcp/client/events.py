"""Client-side event utilities for MCP.

ProvenanceEnvelope wraps events with client-assessed provenance metadata
for safe injection into LLM context. EventQueue provides priority-aware
buffering for events waiting to be processed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, ClassVar

from mcp.types import EventParams

__all__ = ["EventQueue", "ProvenanceEnvelope"]


@dataclass
class ProvenanceEnvelope:
    """Client-side provenance wrapper for events injected into LLM context.

    Clients generate this locally when honoring inject_context effects.
    The server_trust field MUST be client-assessed, never server-supplied.
    """

    server: str
    server_trust: str  # Client-assessed trust tier (e.g., "trusted", "unknown")
    topic: str
    source: str | None = None
    event_id: str | None = None
    received_at: str | None = None  # ISO 8601, client-stamped

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None values."""
        d: dict[str, Any] = {
            "server": self.server,
            "server_trust": self.server_trust,
            "topic": self.topic,
        }
        if self.source is not None:
            d["source"] = self.source
        if self.event_id is not None:
            d["event_id"] = self.event_id
        if self.received_at is not None:
            d["received_at"] = self.received_at
        return d

    def to_xml(self, payload_text: str = "") -> str:
        """Format as XML element for LLM context injection.

        Args:
            payload_text: The event payload as a string (JSON or otherwise).
                          Inserted as the element body.

        Note: All attribute values are XML-escaped via quoteattr to prevent
        injection from attacker-controlled field values.
        """
        from xml.sax.saxutils import escape, quoteattr  # noqa: PLC0415

        attrs = " ".join(
            f"{k}={quoteattr(str(v))}" for k, v in self.to_dict().items()
        )
        return f"<mcp:event {attrs}>{escape(payload_text)}</mcp:event>"

    @classmethod
    def from_event(
        cls,
        event: EventParams,
        *,
        server: str,
        server_trust: str,
    ) -> ProvenanceEnvelope:
        """Create an envelope from an EventParams notification.

        Extracts topic, source, and event_id from the event and stamps
        received_at with the current UTC time.
        """
        from datetime import datetime, timezone  # noqa: PLC0415

        return cls(
            server=server,
            server_trust=server_trust,
            topic=event.topic,
            source=event.source,
            event_id=event.eventId,
            received_at=datetime.now(timezone.utc).isoformat(),
        )


class EventQueue:
    """Priority-aware event buffer for client-side processing.

    Events are enqueued with a priority derived from their requested_effects.
    drain() returns events in priority order (urgent > high > normal > low).
    """

    _PRIORITY_ORDER: ClassVar[dict[str, int]] = {
        "urgent": 0,
        "high": 1,
        "normal": 2,
        "low": 3,
    }

    def __init__(self) -> None:
        self._queues: dict[str, deque[EventParams]] = {
            p: deque() for p in self._PRIORITY_ORDER
        }

    def enqueue(self, event: EventParams) -> None:
        """Add an event to the appropriate priority queue.

        Priority is derived from the highest-priority requested_effect.
        Events with no requested_effects default to "normal".
        """
        priority = self._resolve_priority(event)
        self._queues[priority].append(event)

    def drain(self, max_count: int | None = None) -> list[EventParams]:
        """Remove and return events in priority order.

        Args:
            max_count: Maximum events to return. None means drain all.

        Returns:
            Events ordered urgent -> high -> normal -> low.
        """
        result: list[EventParams] = []
        for priority in self._PRIORITY_ORDER:
            q = self._queues[priority]
            while q:
                if max_count is not None and len(result) >= max_count:
                    return result
                result.append(q.popleft())
        return result

    def __len__(self) -> int:
        return sum(len(q) for q in self._queues.values())

    def __bool__(self) -> bool:
        return any(self._queues.values())

    def _resolve_priority(self, event: EventParams) -> str:
        """Determine priority from highest-priority requested_effect."""
        if not event.requestedEffects:
            return "normal"
        best = "low"
        best_rank = self._PRIORITY_ORDER["low"]
        for effect in event.requestedEffects:
            rank = self._PRIORITY_ORDER.get(effect.priority, best_rank)
            if rank < best_rank:
                best = effect.priority
                best_rank = rank
        return best
