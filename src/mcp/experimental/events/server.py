"""The server side of MCP Events (SEP-3415): `Events`, an `MCPServer` extension.

```python
events = Events(webhooks=Webhooks())
incidents = events.event("incident.created", arguments=IncidentFilter, payload=Incident)

@incidents.match
def same_service(arguments: IncidentFilter, incident: Incident) -> bool:
    return arguments.service == incident.service

mcp = MCPServer("pager", extensions=[events])
...
incidents.emit(Incident(service="billing", title="Latency spike"))
```
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from typing import Any, TypeVar

import anyio
import httpx2
from anyio.abc import TaskGroup
from mcp_types import INVALID_PARAMS
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel, ValidationError

from mcp.experimental.events._buffer import EmitBuffer
from mcp.experimental.events._locks import KeyedLocks
from mcp.experimental.events.event_type import EventBatch, EventQuery, EventType, NoArguments, Occurrence, Subscriber
from mcp.experimental.events.types import (
    EXTENSION_ID,
    FORBIDDEN,
    NOT_FOUND,
    UNSUPPORTED,
    DeliveryMode,
    ListEventsParams,
    ListEventsResult,
    PollEventsParams,
    PollEventsResult,
    SubscribeEventsParams,
    SubscribeEventsResult,
    UnsubscribeEventsParams,
    UnsubscribeEventsResult,
    events_error,
)
from mcp.experimental.events.webhooks import Webhooks, WebhookSubscriptions
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import principal_components
from mcp.server.context import ServerRequestContext
from mcp.server.extension import Extension, MethodBinding
from mcp.server.request_state import compact_json
from mcp.shared.exceptions import MCPError

__all__ = [
    "EventBatch",
    "EventQuery",
    "EventType",
    "Events",
    "NoArguments",
    "Occurrence",
    "Subscriber",
    "Webhooks",
    "access_token_principal",
]

ArgsT = TypeVar("ArgsT", bound=BaseModel)
PayloadT = TypeVar("PayloadT", bound=BaseModel)

PrincipalResolver = Callable[[ServerRequestContext[Any, Any]], str | None]


def access_token_principal(ctx: ServerRequestContext[Any, Any]) -> str | None:
    """The caller's OAuth identity (client, issuer, subject), or `None` on an unauthenticated server."""
    token = get_access_token()
    return compact_json(principal_components(token)) if token is not None else None


class Events(Extension):
    """Offer events to clients, delivered by poll and, with `webhooks=`, by webhook.

    Args:
        webhooks: Enables webhook delivery. Webhook calls need an authenticated principal.
        principal: Who is calling. Subscriptions and poll leases are scoped to it.
        poll_interval: How long clients wait between polls, and how often webhook loops
            run check functions. A check function's `EventBatch.next_poll` overrides it.
        poll_lease: How long after its last poll a poll subscription counts as ended,
            firing `on_unsubscribe`. Defaults to three poll intervals.
        max_events: The most events one poll returns when the client sets no `maxEvents`.
        buffer_size: How many emitted events each event type keeps for readers.
        buffer_max_age: How long an emitted event stays readable.
    """

    identifier = EXTENSION_ID

    def __init__(
        self,
        *,
        webhooks: Webhooks | None = None,
        principal: PrincipalResolver = access_token_principal,
        poll_interval: timedelta = timedelta(seconds=5),
        poll_lease: timedelta | None = None,
        max_events: int = 100,
        buffer_size: int = 1000,
        buffer_max_age: timedelta = timedelta(minutes=10),
    ) -> None:
        self._webhooks = webhooks
        self._principal = principal
        self._poll_interval = poll_interval
        self._poll_lease = poll_lease or poll_interval * 3
        self._max_events = max_events
        self._buffer_size = buffer_size
        self._buffer_max_age = buffer_max_age
        self._event_types: dict[str, EventType[Any, Any]] = {}
        self._leases: dict[str, anyio.CancelScope] = {}
        self._lease_setup = KeyedLocks()
        self._task_group: TaskGroup | None = None
        self._subscriptions: WebhookSubscriptions | None = None

    def event(
        self, name: str, *, arguments: type[ArgsT], payload: type[PayloadT], description: str | None = None
    ) -> EventType[ArgsT, PayloadT]:
        """Declare an event type. `arguments` is what subscribers pass; `payload` is what each event carries.

        Raises:
            ValueError: An event type with this name already exists.
        """
        if name in self._event_types:
            raise ValueError(f"event type {name!r} is already registered")
        buffer = EmitBuffer[PayloadT](self._buffer_size, self._buffer_max_age)
        event_type = EventType(name, arguments=arguments, payload=payload, description=description, buffer=buffer)
        self._event_types[name] = event_type
        return event_type

    def methods(self) -> Sequence[MethodBinding]:
        versions = frozenset(MODERN_PROTOCOL_VERSIONS)
        bindings = [
            MethodBinding("events/list", ListEventsParams, self._list, protocol_versions=versions),
            MethodBinding("events/poll", PollEventsParams, self._poll, protocol_versions=versions),
        ]
        if self._webhooks is not None:
            bindings.append(MethodBinding("events/subscribe", SubscribeEventsParams, self._subscribe, versions))
            bindings.append(MethodBinding("events/unsubscribe", UnsubscribeEventsParams, self._unsubscribe, versions))
        return bindings

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        if self._task_group is not None:
            # shortcut: a nested run (an in-memory Client per connection) shares the outer one's
            # background work, which stops when the outer run does; give each server its own Events.
            yield
            return
        async with AsyncExitStack() as stack:
            webhooks = self._webhooks
            client = None if webhooks is None else webhooks.http_client
            if webhooks is not None and client is None:
                client = await stack.enter_async_context(httpx2.AsyncClient(timeout=5))
            self._task_group = await stack.enter_async_context(anyio.create_task_group())
            if webhooks is not None and client is not None:
                self._subscriptions = WebhookSubscriptions(webhooks, client, self._task_group, self._poll_interval)
            try:
                yield
            finally:
                self._task_group.cancel_scope.cancel()
                self._task_group = self._subscriptions = None
                self._leases.clear()

    async def _list(self, ctx: ServerRequestContext[Any, Any], params: ListEventsParams) -> ListEventsResult:
        delivery: list[DeliveryMode] = ["poll", "webhook"] if self._webhooks is not None else ["poll"]
        return ListEventsResult(events=[event_type.descriptor(delivery) for event_type in self._event_types.values()])

    async def _poll(self, ctx: ServerRequestContext[Any, Any], params: PollEventsParams) -> PollEventsResult:
        event_type, arguments = self._resolve(params.name, params.arguments)
        principal = self._principal(ctx)
        if event_type.subscribe_hooks or event_type.unsubscribe_hooks:
            await self._renew_lease(event_type, arguments, principal)
        max_age = timedelta(milliseconds=params.max_age_ms) if params.max_age_ms is not None else None
        query = EventQuery(arguments, params.cursor, principal, max_age, params.max_events or self._max_events)
        batch = await event_type.read(query)
        return PollEventsResult(
            events=[event_type.wire(occurrence) for occurrence in batch.events],
            cursor=batch.cursor,
            truncated=batch.truncated,
            has_more=batch.has_more,
            next_poll_ms=int((batch.next_poll or self._poll_interval).total_seconds() * 1000),
        )

    async def _subscribe(
        self, ctx: ServerRequestContext[Any, Any], params: SubscribeEventsParams
    ) -> SubscribeEventsResult:
        event_type, arguments = self._resolve(params.name, params.arguments)
        if params.delivery.mode != "webhook":
            raise events_error(UNSUPPORTED, feature="deliveryMode", value=params.delivery.mode)
        if (principal := self._principal(ctx)) is None:
            raise events_error(FORBIDDEN, reason="webhook subscriptions need an authenticated principal")
        assert self._subscriptions is not None, "Events runs inside the server's lifespan"
        return await self._subscriptions.subscribe(event_type, arguments, principal, params)

    async def _unsubscribe(
        self, ctx: ServerRequestContext[Any, Any], params: UnsubscribeEventsParams
    ) -> UnsubscribeEventsResult:
        event_type, _ = self._resolve(params.name, params.arguments)
        if (principal := self._principal(ctx)) is None:
            raise events_error(FORBIDDEN, reason="webhook subscriptions need an authenticated principal")
        assert self._subscriptions is not None, "Events runs inside the server's lifespan"
        self._subscriptions.unsubscribe(event_type, principal, params)
        return UnsubscribeEventsResult()

    def _resolve(self, name: str, arguments: dict[str, Any] | None) -> tuple[EventType[Any, Any], BaseModel]:
        if (event_type := self._event_types.get(name)) is None:
            raise events_error(NOT_FOUND, kind="event", name=name)
        try:
            return event_type, event_type.arguments.model_validate(arguments or {})
        except ValidationError as exc:
            errors = exc.errors(include_url=False, include_context=False, include_input=False)
            raise MCPError(INVALID_PARAMS, f"Invalid arguments for event {name!r}", errors) from None

    async def _renew_lease(self, event_type: EventType[Any, Any], arguments: BaseModel, principal: str | None) -> None:
        key = json.dumps([principal, event_type.name, arguments.model_dump(mode="json")], sort_keys=True)
        deadline = anyio.current_time() + self._poll_lease.total_seconds()
        assert self._task_group is not None, "Events runs inside the server's lifespan"
        subscription_id = f"sub_{hashlib.sha256(key.encode()).hexdigest()[:16]}"
        subscriber = Subscriber(id=subscription_id, arguments=arguments, principal=principal, mode="poll")
        async with self._lease_setup(key):
            if (lease := self._leases.get(key)) is not None:
                lease.deadline = deadline
                return
            for hook in event_type.subscribe_hooks:
                await hook(subscriber)
            lease = self._leases[key] = anyio.CancelScope(deadline=deadline)
            self._task_group.start_soon(self._expire_lease, key, lease, event_type, subscriber)

    async def _expire_lease(
        self, key: str, lease: anyio.CancelScope, event_type: EventType[Any, Any], subscriber: Subscriber[Any]
    ) -> None:
        with lease:
            await anyio.sleep_forever()
        del self._leases[key]
        for hook in event_type.unsubscribe_hooks:
            await hook(subscriber)
