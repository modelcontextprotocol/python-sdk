"""The client side of MCP Events (SEP-3415): `Events`, a `Client` extension.

```python
async with Client(url, extensions=[Events()]) as client:
    events = client.extension(Events)
    async for batch in events.watch("incident.created", {"service": "billing"}, cursor=load_cursor()):
        for event in batch.events:
            handle(event)
        save_cursor(batch.cursor)
```
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio

from mcp.client.extension import ClientExtension
from mcp.client.session import ClientSession
from mcp.experimental.events.types import (
    EXTENSION_ID,
    EventDescriptor,
    ListEventsParams,
    ListEventsRequest,
    ListEventsResult,
    PollEventsParams,
    PollEventsRequest,
    PollEventsResult,
    SubscribeEventsParams,
    SubscribeEventsRequest,
    SubscribeEventsResult,
    UnsubscribeEventsParams,
    UnsubscribeEventsRequest,
    UnsubscribeEventsResult,
    WebhookDelivery,
    WebhookTarget,
)

__all__ = ["Events", "EventsClient"]


class Events(ClientExtension):
    """Register with `Client(extensions=[Events()])`, then use `client.extension(Events)`.

    Args:
        min_poll_interval: The shortest wait between polls, whatever the server asks for,
            so a misbehaving server cannot drive a tight loop.
    """

    identifier = EXTENSION_ID

    def __init__(self, *, min_poll_interval: timedelta = timedelta(seconds=1)) -> None:
        self._min_poll_interval = min_poll_interval

    def bind(self, session: ClientSession) -> EventsClient:
        """Return the events verbs bound to `session`."""
        return EventsClient(session, self._min_poll_interval)


class EventsClient:
    """The events verbs bound to one connected session. Obtain it from `client.extension(Events)`."""

    def __init__(self, session: ClientSession, min_poll_interval: timedelta) -> None:
        self._session = session
        self._min_poll_interval = min_poll_interval

    async def list(self) -> list[EventDescriptor]:
        """Return every event type the server offers, following pagination."""
        descriptors: list[EventDescriptor] = []
        cursor: str | None = None
        while True:
            request = ListEventsRequest(params=ListEventsParams(cursor=cursor))
            result = await self._session.send_request(request, ListEventsResult)
            descriptors.extend(result.events)
            if (cursor := result.next_cursor) is None:
                return descriptors

    async def poll(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        cursor: str | None = None,
        max_age: timedelta | None = None,
        max_events: int | None = None,
    ) -> PollEventsResult:
        """Read the events after `cursor` once. A `None` cursor returns no events, only the current position."""
        params = PollEventsParams(
            name=name,
            arguments=arguments,
            cursor=cursor,
            max_age_ms=int(max_age.total_seconds() * 1000) if max_age is not None else None,
            max_events=max_events,
        )
        return await self._session.send_request(PollEventsRequest(params=params), PollEventsResult)

    async def watch(
        self, name: str, arguments: dict[str, Any] | None = None, *, cursor: str | None = None
    ) -> AsyncGenerator[PollEventsResult, None]:
        """Poll forever, yielding every batch, including empty ones.

        Persist `batch.cursor` after handling a batch, and pass it back after a restart
        to resume: delivery is at-least-once, so deduplicate on `event_id`. Empty batches
        still move the cursor, which keeps it inside the upstream's retention window.
        """
        if cursor is None:
            cursor = (await self.poll(name, arguments)).cursor
        while True:
            batch = await self.poll(name, arguments, cursor=cursor)
            cursor = batch.cursor
            yield batch
            if not batch.has_more:
                wait = max(timedelta(milliseconds=batch.next_poll_ms), self._min_poll_interval)
                await anyio.sleep(wait.total_seconds())

    @asynccontextmanager
    async def subscribe(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        url: str,
        secret: str,
        cursor: str | None = None,
        ttl: timedelta | None = None,
    ) -> AsyncIterator[SubscribeEventsResult]:
        """Hold a webhook subscription: events are POSTed to `url`, signed with `secret`.

        The subscription is refreshed in the background before it expires, and removed on exit.
        Receive the deliveries with `mcp.experimental.events.receiver.WebhookReceiver`.

        Raises:
            MCPError: The server refused the subscription, e.g. because `url` failed verification.
        """
        params = SubscribeEventsParams(
            name=name,
            arguments=arguments,
            delivery=WebhookDelivery(url=url, secret=secret),
            cursor=cursor,
            ttl_ms=int(ttl.total_seconds() * 1000) if ttl is not None else None,
        )
        result = await self._session.send_request(SubscribeEventsRequest(params=params), SubscribeEventsResult)
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(self._refresh, params, result)
            try:
                yield result
            finally:
                task_group.cancel_scope.cancel()
                unsubscribe = UnsubscribeEventsParams(name=name, arguments=arguments, delivery=WebhookTarget(url=url))
                with anyio.CancelScope(shield=True):
                    request = UnsubscribeEventsRequest(params=unsubscribe)
                    await self._session.send_request(request, UnsubscribeEventsResult)

    async def _refresh(self, params: SubscribeEventsParams, result: SubscribeEventsResult) -> None:
        while result.refresh_before is not None:
            # Refresh at two thirds of the remaining lifetime, leaving room for a failed attempt.
            await anyio.sleep((result.refresh_before - datetime.now(UTC)).total_seconds() * 2 / 3)
            # The latest safe cursor is a no-op for a live subscription, and the replay point if the server lost it.
            request = SubscribeEventsRequest(params=params.model_copy(update={"cursor": result.cursor}))
            result = await self._session.send_request(request, SubscribeEventsResult)
