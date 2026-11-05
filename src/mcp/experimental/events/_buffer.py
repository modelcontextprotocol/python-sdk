"""The in-memory ring buffer that serves event types fed by `EventType.emit`."""

from __future__ import annotations

import secrets
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Generic, TypeVar

import anyio
from pydantic import BaseModel

from mcp.experimental.events.event_type import EventBatch, Occurrence

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class EmitBuffer(Generic[PayloadT]):
    """Recent emitted events, addressed by process-local cursors.

    A cursor is `<epoch>.<sequence>`. The epoch is random per process, so a cursor
    from before a restart reads as unknown, and the reader starts again from now
    with `truncated` set, as SEP-3415 prescribes for emit-only event types.
    """

    def __init__(self, max_events: int, max_age: timedelta) -> None:
        self._epoch = secrets.token_hex(4)
        self._entries: deque[tuple[int, Occurrence[PayloadT]]] = deque(maxlen=max_events)
        self._max_age = max_age
        self._head = 0
        self._appended = anyio.Event()

    def append(self, occurrence: Occurrence[PayloadT]) -> None:
        self._head += 1
        self._entries.append((self._head, occurrence))
        self._appended.set()
        self._appended = anyio.Event()

    async def wait(self, timeout: float) -> None:
        """Return once an event is appended, or after `timeout` seconds."""
        with anyio.move_on_after(timeout):
            await self._appended.wait()

    def read(
        self,
        cursor: str | None,
        *,
        max_age: timedelta | None,
        max_events: int | None,
        select: Callable[[PayloadT], PayloadT | None],
    ) -> EventBatch[PayloadT]:
        now = datetime.now(UTC)
        while self._entries and self._entries[0][1].timestamp < now - self._max_age:
            self._entries.popleft()
        position = self._position(cursor)
        if position is None:
            return EventBatch(cursor=f"{self._epoch}.{self._head}", truncated=cursor is not None)
        oldest = self._entries[0][0] if self._entries else self._head + 1
        truncated = position < oldest - 1
        floor = now - max_age if max_age is not None else None
        events: list[Occurrence[PayloadT]] = []
        has_more = False
        for sequence, occurrence in self._entries:
            if sequence <= position:
                continue
            if max_events is not None and len(events) == max_events:
                has_more = True
                break
            position = sequence
            if floor is not None and occurrence.timestamp < floor:
                truncated = True
                continue
            if (data := select(occurrence.data)) is not None:
                events.append(Occurrence(data=data, id=occurrence.id, timestamp=occurrence.timestamp))
        return EventBatch(cursor=f"{self._epoch}.{position}", events=events, truncated=truncated, has_more=has_more)

    def _position(self, cursor: str | None) -> int | None:
        epoch, _, sequence = (cursor or "").partition(".")
        if epoch != self._epoch or not sequence.isdigit() or int(sequence) > self._head:
            return None
        return int(sequence)
