"""Tests for the client side of MCP Events (SEP-3415): `list`, `watch`, and `subscribe`'s refresh loop.

Webhook subscribe against the SDK's own server is covered in `test_webhooks.py`.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import pytest
from pydantic import BaseModel

from mcp.client.client import Client
from mcp.experimental.events.client import Events as ClientEvents
from mcp.experimental.events.server import EventBatch, EventQuery, Events, NoArguments, Occurrence
from mcp.experimental.events.types import (
    EXTENSION_ID,
    EventDescriptor,
    ListEventsParams,
    ListEventsResult,
    SubscribeEventsParams,
    SubscribeEventsResult,
    UnsubscribeEventsParams,
    UnsubscribeEventsResult,
)
from mcp.server.context import ServerRequestContext
from mcp.server.extension import Extension, MethodBinding
from mcp.server.mcpserver import MCPServer

pytestmark = pytest.mark.anyio


class Ping(BaseModel):
    n: int


async def test_watch_yields_batches_with_events_and_resumes_from_the_latest_cursor() -> None:
    """`watch` polls in a loop, drains `hasMore` batches at once, skips empty polls, and yields
    batches that carry events or a gap (SDK-defined loop over spec-mandated poll semantics)."""
    events = Events(poll_interval=timedelta(0), max_events=2)
    pings = events.event("ping", arguments=NoArguments, payload=Ping)
    mcp = MCPServer("pinger", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents(min_poll_interval=timedelta(0))]) as client:
        events_client = client.extension(ClientEvents)
        start = await events_client.poll("ping")
        for n in range(3):
            pings.emit(Ping(n=n))
        watch = events_client.watch("ping", cursor=start.cursor)
        with anyio.fail_after(5):
            first = await anext(watch)
            second = await anext(watch)
            await watch.aclose()

    assert [e.data for e in first.events] == [{"n": 0}, {"n": 1}]
    assert first.has_more is True
    assert [e.data for e in second.events] == [{"n": 2}]


async def test_watch_from_a_saved_cursor_yields_the_gap_when_the_cursor_is_unknown() -> None:
    """Resuming from a cursor the server cannot read yields a `truncated` batch so the caller can
    reconcile (spec-mandated gap signal)."""
    events = Events(poll_interval=timedelta(0))
    events.event("ping", arguments=NoArguments, payload=Ping)
    mcp = MCPServer("pinger", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents(min_poll_interval=timedelta(0))]) as client:
        watch = client.extension(ClientEvents).watch("ping", cursor="from-a-previous-life")
        with anyio.fail_after(5):
            batch = await anext(watch)
            await watch.aclose()

    assert (batch.events, batch.truncated) == ([], True)


async def test_watch_waits_at_least_the_clients_floor_between_polls() -> None:
    """The client's `min_poll_interval` overrides a server asking for a tighter loop (spec-mandated floor;
    a time-based feature, so the test lets one floor elapse)."""
    polls: list[str | None] = []
    events = Events(poll_interval=timedelta(0))
    pings = events.event("ping", arguments=NoArguments, payload=Ping)

    @pings.check
    async def check(query: EventQuery[NoArguments]) -> EventBatch[Ping]:
        polls.append(query.cursor)
        if len(polls) < 3:
            return EventBatch(cursor="c")
        return EventBatch(cursor="c", events=[Occurrence(Ping(n=len(polls)))])

    mcp = MCPServer("pinger", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents(min_poll_interval=timedelta(milliseconds=20))]) as client:
        watch = client.extension(ClientEvents).watch("ping")
        with anyio.fail_after(5):
            batch = await anext(watch)
            await watch.aclose()

    assert polls == [None, "c", "c"]
    assert [e.data for e in batch.events] == [{"n": 3}]


class _OtherEventsServer(Extension):
    """A third-party Events server: pages `events/list`, and grants a short-lived webhook subscription
    that it then stops expiring. The SDK's own server can do neither."""

    identifier = EXTENSION_ID

    def __init__(self) -> None:
        self.subscribes: list[SubscribeEventsParams] = []
        self.refreshed = anyio.Event()
        self.unsubscribed = anyio.Event()

    def methods(self) -> list[MethodBinding]:
        return [
            MethodBinding("events/list", ListEventsParams, self._list),
            MethodBinding("events/subscribe", SubscribeEventsParams, self._subscribe),
            MethodBinding("events/unsubscribe", UnsubscribeEventsParams, self._unsubscribe),
        ]

    async def _list(self, ctx: ServerRequestContext[Any, Any], params: ListEventsParams) -> ListEventsResult:
        name = "first" if params.cursor is None else "second"
        descriptor = EventDescriptor(name=name, delivery=["poll"], input_schema={}, payload_schema={})
        return ListEventsResult(events=[descriptor], next_cursor="page-2" if params.cursor is None else None)

    async def _subscribe(
        self, ctx: ServerRequestContext[Any, Any], params: SubscribeEventsParams
    ) -> SubscribeEventsResult:
        self.subscribes.append(params)
        if len(self.subscribes) == 1:
            return SubscribeEventsResult(id="sub-1", refresh_before=datetime.now(UTC) + timedelta(milliseconds=30))
        self.refreshed.set()
        return SubscribeEventsResult(id="sub-1", refresh_before=None)

    async def _unsubscribe(
        self, ctx: ServerRequestContext[Any, Any], params: UnsubscribeEventsParams
    ) -> UnsubscribeEventsResult:
        self.unsubscribed.set()
        return UnsubscribeEventsResult()


async def test_list_follows_pagination_to_the_last_page() -> None:
    """`list` returns every page's event types (spec-mandated pagination)."""
    mcp = MCPServer("other", extensions=[_OtherEventsServer()])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        descriptors = await client.extension(ClientEvents).list()

    assert [d.name for d in descriptors] == ["first", "second"]


async def test_subscribe_refreshes_before_the_subscription_expires_and_unsubscribes_on_exit() -> None:
    """`subscribe` resends the subscription before `refreshBefore`, stops once the server grants no
    expiry, and unsubscribes when the block exits (spec-mandated refresh; a time-based feature)."""
    server = _OtherEventsServer()
    mcp = MCPServer("other", extensions=[server])
    secret = "whsec_" + "a" * 43 + "="

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        events_client = client.extension(ClientEvents)
        async with events_client.subscribe("first", url="https://client.test/hooks", secret=secret, cursor="c0"):
            with anyio.fail_after(5):
                await server.refreshed.wait()
        with anyio.fail_after(5):
            await server.unsubscribed.wait()

    first, refresh = server.subscribes
    assert (first.cursor, refresh.cursor) == ("c0", None)
    assert refresh.delivery == first.delivery
