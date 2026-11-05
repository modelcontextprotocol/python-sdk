"""Tests for the server side of MCP Events (SEP-3415): `events/list`, `events/poll`, and poll leases.

Webhook delivery is covered in `test_webhooks.py`.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import pytest
from inline_snapshot import snapshot
from mcp_types import INVALID_PARAMS
from pydantic import BaseModel, ConfigDict

from mcp.client.client import Client
from mcp.experimental.events.client import Events as ClientEvents
from mcp.experimental.events.server import (
    EventBatch,
    EventQuery,
    Events,
    NoArguments,
    Occurrence,
    Subscriber,
    Webhooks,
)
from mcp.experimental.events.types import EXTENSION_ID, NOT_FOUND, PollEventsParams, PollEventsRequest
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError

pytestmark = pytest.mark.anyio


class ServiceFilter(BaseModel):
    service: str


class Incident(BaseModel):
    service: str
    title: str


class _RawResult(BaseModel):
    model_config = ConfigDict(extra="allow")


async def test_events_list_describes_each_event_type_with_json_schemas() -> None:
    """`events/list` derives `inputSchema`/`payloadSchema` from the Pydantic models, and lists poll alone
    without webhooks (spec-mandated shape, SDK-defined schema source)."""
    events = Events()
    events.event("incident.created", arguments=ServiceFilter, payload=Incident, description="A new incident")
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        descriptors = await client.extension(ClientEvents).list()
        capabilities = client.server_capabilities

    assert capabilities.extensions == {EXTENSION_ID: {}}
    assert [d.model_dump(by_alias=True, exclude_none=True) for d in descriptors] == snapshot(
        [
            {
                "name": "incident.created",
                "description": "A new incident",
                "delivery": ["poll"],
                "inputSchema": {
                    "properties": {"service": {"title": "Service", "type": "string"}},
                    "required": ["service"],
                    "title": "ServiceFilter",
                    "type": "object",
                },
                "payloadSchema": {
                    "properties": {
                        "service": {"title": "Service", "type": "string"},
                        "title": {"title": "Title", "type": "string"},
                    },
                    "required": ["service", "title"],
                    "title": "Incident",
                    "type": "object",
                },
            }
        ]
    )


async def test_events_list_offers_webhook_when_webhooks_are_configured() -> None:
    """Configuring `Webhooks` adds webhook to every event type's delivery modes (SDK-defined)."""
    events = Events(webhooks=Webhooks())
    events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        [descriptor] = await client.extension(ClientEvents).list()

    assert descriptor.delivery == ["poll", "webhook"]


async def test_poll_returns_emitted_events_that_match_the_subscription_after_the_cursor() -> None:
    """A null cursor returns only the current position; the next poll returns the events emitted
    since, filtered by `match` and shaped by `transform` (spec-mandated cursor semantics)."""
    events = Events()
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)

    @incidents.match
    def same_service(arguments: ServiceFilter, incident: Incident) -> bool:
        return arguments.service == incident.service

    @incidents.transform
    def shout(arguments: ServiceFilter, incident: Incident) -> Incident:
        return incident.model_copy(update={"title": incident.title.upper()})

    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        events_client = client.extension(ClientEvents)
        incidents.emit(Incident(service="billing", title="before the subscription"))
        start = await events_client.poll("incident.created", {"service": "billing"})
        incidents.emit(Occurrence(Incident(service="billing", title="latency"), id="inc-1"))
        incidents.emit(Incident(service="search", title="someone else's"))
        batch = await events_client.poll("incident.created", {"service": "billing"}, cursor=start.cursor)

    assert start.events == []
    assert [(event.event_id, event.data) for event in batch.events] == [
        ("inc-1", {"service": "billing", "title": "LATENCY"})
    ]
    assert (batch.truncated, batch.has_more, batch.next_poll_ms) == (False, False, 5000)


async def test_poll_result_on_the_wire_uses_camel_case_and_a_complete_result_type() -> None:
    """The poll result carries `resultType: "complete"` and camelCase fields (spec-mandated)."""
    events = Events(poll_interval=timedelta(seconds=30))
    events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp) as client:
        request = PollEventsRequest(params=PollEventsParams(name="incident.created", arguments={"service": "a"}))
        result = await client.session.send_request(request, _RawResult)

    dumped = result.model_dump()
    dumped.pop("_meta")
    assert dumped.pop("cursor") is not None
    assert dumped == snapshot(
        {
            "resultType": "complete",
            "events": [],
            "truncated": False,
            "hasMore": False,
            "nextPollMs": 30000,
        }
    )


async def test_poll_with_max_events_returns_a_partial_batch_and_has_more() -> None:
    """When more events are pending than `maxEvents`, the poll returns that many with `hasMore`,
    and the next poll continues from the intermediate cursor (spec-mandated)."""
    events = Events()
    pings = events.event("ping", arguments=NoArguments, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        events_client = client.extension(ClientEvents)
        start = await events_client.poll("ping")
        for title in ("a", "b", "c"):
            pings.emit(Incident(service="s", title=title))
        first = await events_client.poll("ping", cursor=start.cursor, max_events=2)
        rest = await events_client.poll("ping", cursor=first.cursor, max_events=2)

    assert [e.data["title"] for e in first.events] == ["a", "b"]
    assert first.has_more is True
    assert [e.data["title"] for e in rest.events] == ["c"]
    assert rest.has_more is False


async def test_poll_with_an_unknown_cursor_restarts_from_now_and_reports_truncated() -> None:
    """A cursor the server cannot read (e.g. from before a restart) returns a fresh cursor and
    `truncated: true`, never an error (spec-mandated)."""
    events = Events()
    pings = events.event("ping", arguments=NoArguments, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        events_client = client.extension(ClientEvents)
        pings.emit(Incident(service="s", title="a"))
        batch = await events_client.poll("ping", cursor="from-another-server.1")
        after = await events_client.poll("ping", cursor=batch.cursor)

    assert (batch.events, batch.truncated) == ([], True)
    assert (after.events, after.truncated) == ([], False)


async def test_poll_reports_truncated_when_the_buffer_dropped_events_after_the_cursor() -> None:
    """Events that fell out of the bounded buffer are a gap: the poll returns what is left with
    `truncated: true` (spec-mandated gap signal, SDK-defined buffer)."""
    events = Events(buffer_size=2)
    pings = events.event("ping", arguments=NoArguments, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        events_client = client.extension(ClientEvents)
        start = await events_client.poll("ping")
        for title in ("a", "b", "c"):
            pings.emit(Incident(service="s", title=title))
        batch = await events_client.poll("ping", cursor=start.cursor)

    assert [e.data["title"] for e in batch.events] == ["b", "c"]
    assert batch.truncated is True


async def test_poll_skips_events_older_than_max_age_and_reports_truncated() -> None:
    """`maxAgeMs` bounds replay; skipped events are reported as `truncated` (spec-mandated)."""
    events = Events()
    pings = events.event("ping", arguments=NoArguments, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        events_client = client.extension(ClientEvents)
        start = await events_client.poll("ping")
        old = datetime.now(UTC) - timedelta(minutes=5)
        pings.emit(Occurrence(Incident(service="s", title="old"), timestamp=old))
        pings.emit(Incident(service="s", title="new"))
        batch = await events_client.poll("ping", cursor=start.cursor, max_age=timedelta(minutes=1))

    assert [e.data["title"] for e in batch.events] == ["new"]
    assert batch.truncated is True


async def test_emitted_events_older_than_buffer_max_age_are_dropped() -> None:
    """The buffer forgets events past `buffer_max_age`, so a reader behind them sees a gap (SDK-defined)."""
    events = Events(buffer_max_age=timedelta(minutes=1))
    pings = events.event("ping", arguments=NoArguments, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        events_client = client.extension(ClientEvents)
        start = await events_client.poll("ping")
        pings.emit(Occurrence(Incident(service="s", title="stale"), timestamp=datetime.now(UTC) - timedelta(hours=1)))
        batch = await events_client.poll("ping", cursor=start.cursor)

    assert (batch.events, batch.truncated) == ([], True)


async def test_poll_answers_from_the_check_function_with_the_callers_query() -> None:
    """A check function receives the validated arguments, cursor, and principal, and its batch
    becomes the poll result; a null cursor still returns no events (SDK-defined, spec-mandated null cursor)."""
    queries: list[EventQuery[ServiceFilter]] = []
    events = Events(principal=lambda ctx: "alice")
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)

    @incidents.check
    async def check(query: EventQuery[ServiceFilter]) -> EventBatch[Incident]:
        queries.append(query)
        incident = Occurrence(Incident(service=query.arguments.service, title="from upstream"), id="up-1")
        return EventBatch(cursor="upstream-7", events=[incident], next_poll=timedelta(seconds=1))

    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        events_client = client.extension(ClientEvents)
        start = await events_client.poll("incident.created", {"service": "billing"})
        batch = await events_client.poll("incident.created", {"service": "billing"}, cursor="upstream-6")

    assert (start.events, start.cursor) == ([], "upstream-7")
    assert [(e.event_id, e.data["title"]) for e in batch.events] == [("up-1", "from upstream")]
    assert (batch.cursor, batch.next_poll_ms) == ("upstream-7", 1000)
    assert [(q.arguments, q.cursor, q.principal, q.max_events) for q in queries] == [
        (ServiceFilter(service="billing"), None, "alice", 100),
        (ServiceFilter(service="billing"), "upstream-6", "alice", 100),
    ]


async def test_poll_for_an_unknown_event_type_raises_not_found() -> None:
    """Polling a name the server does not offer is `NotFound` (spec-mandated)."""
    mcp = MCPServer("pager", extensions=[Events()])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.extension(ClientEvents).poll("nope")

    assert exc_info.value.code == NOT_FOUND
    assert exc_info.value.data == {"kind": "event", "name": "nope"}


async def test_poll_with_arguments_that_fail_validation_raises_invalid_params() -> None:
    """Arguments are validated against the event type's model before any read (SDK-defined)."""
    events = Events()
    events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.extension(ClientEvents).poll("incident.created", {"service": 1})

    assert exc_info.value.code == INVALID_PARAMS
    assert exc_info.value.message == snapshot("Invalid arguments for event 'incident.created'")


def test_registering_an_event_type_twice_raises() -> None:
    """Event type names are unique per server (SDK-defined)."""
    events = Events()
    events.event("ping", arguments=NoArguments, payload=Incident)

    with pytest.raises(ValueError):
        events.event("ping", arguments=NoArguments, payload=Incident)


def test_emitting_on_an_event_type_with_a_check_function_raises() -> None:
    """A check function owns its event type's events, so `emit` is refused (SDK-defined)."""
    events = Events()
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)

    @incidents.check
    async def check(query: EventQuery[ServiceFilter]) -> EventBatch[Incident]:  # pragma: no cover
        raise NotImplementedError

    with pytest.raises(RuntimeError):
        incidents.emit(Incident(service="s", title="t"))


async def test_poll_lease_fires_on_subscribe_once_and_on_unsubscribe_when_polls_stop() -> None:
    """Poll subscriptions are leased: `on_subscribe` fires on the first poll for a key, later polls
    renew the lease, and `on_unsubscribe` fires once it lapses (spec SDK guidance)."""
    seen: list[tuple[str, Subscriber[ServiceFilter]]] = []
    lapsed = anyio.Event()
    # Time-based feature: a short lease, so the test waits for its real expiry.
    events = Events(poll_lease=timedelta(milliseconds=50))
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)

    @incidents.on_subscribe
    async def subscribed(subscriber: Subscriber[ServiceFilter]) -> None:
        seen.append(("subscribe", subscriber))

    @incidents.on_unsubscribe
    async def unsubscribed(subscriber: Subscriber[ServiceFilter]) -> None:
        seen.append(("unsubscribe", subscriber))
        lapsed.set()

    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        events_client = client.extension(ClientEvents)
        await events_client.poll("incident.created", {"service": "billing"})
        await events_client.poll("incident.created", {"service": "billing"})
        with anyio.fail_after(5):
            await lapsed.wait()

    [(first, subscriber), (second, same)] = seen
    assert (first, second) == ("subscribe", "unsubscribe")
    assert subscriber is same
    assert (subscriber.arguments, subscriber.principal, subscriber.mode) == (
        ServiceFilter(service="billing"),
        None,
        "poll",
    )


async def test_failing_on_subscribe_fails_the_poll_and_runs_again_on_the_next_one() -> None:
    """A poll whose `on_subscribe` hook raises does not take the lease, so the next poll retries
    the hook (SDK-defined)."""
    attempts: list[str] = []
    events = Events()
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)

    @incidents.on_subscribe
    async def subscribed(subscriber: Subscriber[ServiceFilter]) -> None:
        attempts.append(subscriber.id)
        if len(attempts) == 1:
            raise MCPError(code=INVALID_PARAMS, message="upstream refused")

    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        events_client = client.extension(ClientEvents)
        with pytest.raises(MCPError):
            await events_client.poll("incident.created", {"service": "billing"})
        await events_client.poll("incident.created", {"service": "billing"})
        assert len(attempts) == 2
        assert attempts[0] == attempts[1]


async def test_concurrent_connections_share_one_running_events_extension() -> None:
    """Every in-memory connection enters the server lifespan; a nested entry reuses the running
    extension, so poll leases keep working on the second connection (pins a known shortcut)."""
    subscribed: list[Any] = []
    events = Events()
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)

    @incidents.on_subscribe
    async def on_subscribe(subscriber: Subscriber[ServiceFilter]) -> None:
        subscribed.append(subscriber.arguments.service)

    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents()]) as first, Client(mcp, extensions=[ClientEvents()]) as second:
        await first.extension(ClientEvents).poll("incident.created", {"service": "a"})
        await second.extension(ClientEvents).poll("incident.created", {"service": "b"})
        assert subscribed == ["a", "b"]
