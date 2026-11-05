"""Event types: what a server offers, and the value objects its authors work with."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Generic, Literal, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict

from mcp.experimental.events.types import EventDescriptor, EventOccurrence

if TYPE_CHECKING:
    from mcp.experimental.events._buffer import EmitBuffer

__all__ = ["EventBatch", "EventQuery", "EventType", "NoArguments", "Occurrence", "Subscriber"]

ArgsT = TypeVar("ArgsT", bound=BaseModel)
PayloadT = TypeVar("PayloadT", bound=BaseModel)


class NoArguments(BaseModel):
    """The arguments of an event type that takes none; any argument is rejected."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Occurrence(Generic[PayloadT]):
    """One event. `id` should be the upstream's stable identifier, so clients can deduplicate."""

    data: PayloadT
    id: str = field(default_factory=partial(secrets.token_hex, 16))
    timestamp: datetime = field(default_factory=partial(datetime.now, UTC))


@dataclass(frozen=True)
class EventQuery(Generic[ArgsT]):
    """What a check function is asked: the events after `cursor` that match `arguments`.

    A `None` cursor means "start from now": return the current position and no events.
    """

    arguments: ArgsT
    cursor: str | None
    principal: str | None = None
    max_age: timedelta | None = None
    max_events: int | None = None


@dataclass(frozen=True)
class EventBatch(Generic[PayloadT]):
    """What a check function answers: the events found, and the cursor after them.

    Return `cursor=None` for an event type that cannot replay. Set `truncated` when the
    events start later than the query's cursor, and `has_more` when you stopped at
    `max_events`. `next_poll` overrides the server's poll interval for this answer.
    """

    cursor: str | None
    events: Sequence[Occurrence[PayloadT]] = ()
    truncated: bool = False
    has_more: bool = False
    next_poll: timedelta | None = None


@dataclass(frozen=True)
class Subscriber(Generic[ArgsT]):
    """A subscription as the lifecycle hooks see it."""

    id: str
    arguments: ArgsT
    principal: str | None
    mode: Literal["poll", "webhook"]


CheckFn: TypeAlias = Callable[[EventQuery[ArgsT]], Awaitable[EventBatch[PayloadT]]]
MatchFn: TypeAlias = Callable[[ArgsT, PayloadT], bool]
TransformFn: TypeAlias = Callable[[ArgsT, PayloadT], PayloadT]
HookFn: TypeAlias = Callable[[Subscriber[ArgsT]], Awaitable[None]]


class EventType(Generic[ArgsT, PayloadT]):
    """An event type a server offers. Create it with `Events.event`.

    Feed it in one of two ways. Register a `check` function when the upstream can answer
    "what happened since this cursor" (Gmail history, a Kafka offset, Stripe `/v1/events`).
    Otherwise call `emit` as events arrive, and the server keeps a bounded buffer for
    readers, filtered per subscriber by `match` and shaped by `transform`.
    """

    def __init__(
        self,
        name: str,
        *,
        arguments: type[ArgsT],
        payload: type[PayloadT],
        description: str | None,
        buffer: EmitBuffer[PayloadT],
    ) -> None:
        self.name = name
        self.arguments = arguments
        self.payload = payload
        self.description = description
        self.buffer = buffer
        self._check: CheckFn[ArgsT, PayloadT] | None = None
        self._match: MatchFn[ArgsT, PayloadT] | None = None
        self._transform: TransformFn[ArgsT, PayloadT] | None = None
        self.subscribe_hooks: list[HookFn[ArgsT]] = []
        self.unsubscribe_hooks: list[HookFn[ArgsT]] = []

    def check(self, fn: CheckFn[ArgsT, PayloadT]) -> CheckFn[ArgsT, PayloadT]:
        """Register the function that answers every read of this event type."""
        self._check = fn
        return fn

    def match(self, fn: MatchFn[ArgsT, PayloadT]) -> MatchFn[ArgsT, PayloadT]:
        """Register who receives an emitted event: `fn(arguments, payload)`. Default: everyone."""
        self._match = fn
        return fn

    def transform(self, fn: TransformFn[ArgsT, PayloadT]) -> TransformFn[ArgsT, PayloadT]:
        """Register how an emitted event is shaped per subscriber: `fn(arguments, payload)`."""
        self._transform = fn
        return fn

    def on_subscribe(self, fn: HookFn[ArgsT]) -> HookFn[ArgsT]:
        """Register a hook run when a subscription starts, to set up upstream listeners."""
        self.subscribe_hooks.append(fn)
        return fn

    def on_unsubscribe(self, fn: HookFn[ArgsT]) -> HookFn[ArgsT]:
        """Register a hook run when a subscription ends or lapses, to tear upstream listeners down."""
        self.unsubscribe_hooks.append(fn)
        return fn

    def emit(self, event: PayloadT | Occurrence[PayloadT]) -> None:
        """Record an event for every current and future reader of this event type.

        Pass an `Occurrence` to set the event's id (for client-side deduplication) or timestamp.

        Raises:
            RuntimeError: The event type has a check function, which owns its events.
        """
        if self._check is not None:
            raise RuntimeError(f"event type {self.name!r} has a check function; it cannot also emit")
        self.buffer.append(event if isinstance(event, Occurrence) else Occurrence(data=event))

    async def read(self, query: EventQuery[ArgsT]) -> EventBatch[PayloadT]:
        if self._check is None:
            return self.buffer.read(
                query.cursor,
                max_age=query.max_age,
                max_events=query.max_events,
                select=lambda payload: self._select(query.arguments, payload),
            )
        batch = await self._check(query)
        # A null cursor means "start from now", whatever the check function returned.
        return replace(batch, events=()) if query.cursor is None else batch

    def descriptor(self, delivery: list[Literal["poll", "push", "webhook"]]) -> EventDescriptor:
        return EventDescriptor(
            name=self.name,
            description=self.description,
            delivery=delivery,
            input_schema=self.arguments.model_json_schema(),
            payload_schema=self.payload.model_json_schema(),
        )

    def wire(self, occurrence: Occurrence[PayloadT], cursor: str | None = None) -> EventOccurrence:
        return EventOccurrence(
            event_id=occurrence.id,
            name=self.name,
            timestamp=occurrence.timestamp,
            data=occurrence.data.model_dump(mode="json", by_alias=True),
            cursor=cursor,
        )

    def _select(self, arguments: ArgsT, payload: PayloadT) -> PayloadT | None:
        if self._match is not None and not self._match(arguments, payload):
            return None
        return self._transform(arguments, payload) if self._transform is not None else payload
