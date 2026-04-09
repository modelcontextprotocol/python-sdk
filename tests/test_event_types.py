"""Tests for MCP event type serialization/deserialization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import anyio
import pytest
from pydantic import ValidationError

from mcp import types
from mcp.client.session import ClientSession
from mcp.server.events import RetainedValueStore, SubscriptionRegistry
from mcp.server.lowlevel import NotificationOptions
from mcp.server.lowlevel.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    ClientRequest,
    EventEffect,
    EventEmitNotification,
    EventListRequest,
    EventListResult,
    EventParams,
    EventsCapability,
    EventSubscribeParams,
    EventSubscribeRequest,
    EventSubscribeResult,
    EventTopicDescriptor,
    EventUnsubscribeParams,
    EventUnsubscribeRequest,
    EventUnsubscribeResult,
    RejectedTopic,
    RetainedEvent,
    ServerCapabilities,
    ServerNotification,
    ServerResult,
    SubscribedTopic,
)


class TestEventEffect:
    def test_basic(self):
        e = EventEffect(type="inject_context", priority="high")
        assert e.type == "inject_context"
        assert e.priority == "high"

    def test_default_priority(self):
        e = EventEffect(type="notify_user")
        assert e.priority == "normal"

    def test_roundtrip(self):
        e = EventEffect(type="trigger_turn", priority="urgent")
        data = e.model_dump(by_alias=True)
        e2 = EventEffect.model_validate(data)
        assert e2.type == e.type
        assert e2.priority == e.priority


class TestEventTopicDescriptor:
    def test_basic(self):
        d = EventTopicDescriptor(pattern="foo/bar", description="A topic", retained=True)
        assert d.pattern == "foo/bar"
        assert d.description == "A topic"
        assert d.retained is True

    def test_schema_alias(self):
        d = EventTopicDescriptor(pattern="x", schema={"type": "object"})
        data = d.model_dump(by_alias=True)
        assert data["schema"] == {"type": "object"}
        assert "schema_" not in data


class TestEventsCapability:
    def test_defaults(self):
        c = EventsCapability()
        assert c.topics == []
        assert c.instructions is None

    def test_with_topics(self):
        c = EventsCapability(
            topics=[
                EventTopicDescriptor(pattern="a/b", description="Alpha-bravo", retained=True),
            ],
            instructions="Subscribe to a/b for updates",
        )
        assert len(c.topics) == 1
        assert c.topics[0].pattern == "a/b"
        assert c.topics[0].description == "Alpha-bravo"
        assert c.topics[0].retained is True
        assert c.instructions == "Subscribe to a/b for updates"


class TestServerCapabilitiesEvents:
    def test_events_field(self):
        caps = ServerCapabilities(events=EventsCapability())
        assert caps.events is not None
        data = caps.model_dump(by_alias=True, exclude_none=True)
        assert "events" in data

    def test_events_none_by_default(self):
        caps = ServerCapabilities()
        assert caps.events is None


class TestEventParams:
    def test_inherits_meta(self):
        """EventParams extends NotificationParams, so it should have _meta."""
        p = EventParams(
            topic="test/topic",
            eventId="abc123",
            payload={"key": "value"},
        )
        assert p.meta is None
        # _meta field should be serializable
        p2 = EventParams(
            topic="test/topic",
            eventId="abc123",
            payload="hello",
            _meta={"related_request_id": "req-1"},
        )
        data = p2.model_dump(by_alias=True)
        assert data["_meta"] == {"related_request_id": "req-1"}

    def test_all_fields(self):
        p = EventParams(
            topic="spellbook/sessions/42/messages",
            eventId="01JXYZ",
            payload={"text": "hello"},
            timestamp="2026-04-07T12:00:00Z",
            retained=True,
            source="spellbook",
            correlationId="corr-1",
            requestedEffects=[EventEffect(type="inject_context")],
            expiresAt="2026-04-08T12:00:00Z",
        )
        data = p.model_dump(by_alias=True, exclude_none=True)
        assert data["topic"] == "spellbook/sessions/42/messages"
        assert data["eventId"] == "01JXYZ"
        assert data["payload"] == {"text": "hello"}
        assert data["timestamp"] == "2026-04-07T12:00:00Z"
        assert data["retained"] is True
        assert data["source"] == "spellbook"
        assert data["correlationId"] == "corr-1"
        assert len(data["requestedEffects"]) == 1
        assert data["expiresAt"] == "2026-04-08T12:00:00Z"


class TestEventEmitNotification:
    def test_method(self):
        n = EventEmitNotification(
            params=EventParams(
                topic="a/b",
                eventId="id1",
                payload=42,
            )
        )
        assert n.method == "events/emit"

    def test_roundtrip_via_root_model(self):
        n = EventEmitNotification(
            params=EventParams(
                topic="a/b",
                eventId="id1",
                payload={"x": 1},
            )
        )
        data = n.model_dump(by_alias=True, mode="json")
        wrapped = ServerNotification.model_validate(data)
        parsed = wrapped.root
        assert isinstance(parsed, EventEmitNotification)
        assert parsed.params.topic == "a/b"
        assert parsed.params.event_id == "id1"
        assert parsed.params.payload == {"x": 1}


class TestEventSubscribeRequest:
    def test_roundtrip_via_root_model(self):
        req = EventSubscribeRequest(params=EventSubscribeParams(topics=["a/+", "b/#"]))
        data = req.model_dump(by_alias=True, mode="json")
        wrapped = ClientRequest.model_validate(data)
        parsed = wrapped.root
        assert isinstance(parsed, EventSubscribeRequest)
        assert parsed.params.topics == ["a/+", "b/#"]


class TestEventUnsubscribeRequest:
    def test_roundtrip_via_root_model(self):
        req = EventUnsubscribeRequest(params=EventUnsubscribeParams(topics=["a/+"]))
        data = req.model_dump(by_alias=True, mode="json")
        wrapped = ClientRequest.model_validate(data)
        parsed = wrapped.root
        assert isinstance(parsed, EventUnsubscribeRequest)
        assert parsed.params.topics == ["a/+"]


class TestEventListRequest:
    def test_roundtrip_via_root_model(self):
        req = EventListRequest()
        data = req.model_dump(by_alias=True, mode="json")
        wrapped = ClientRequest.model_validate(data)
        parsed = wrapped.root
        assert isinstance(parsed, EventListRequest)
        assert parsed.method == "events/list"


class TestResultTypes:
    def test_subscribe_result(self):
        r = EventSubscribeResult(
            subscribed=[SubscribedTopic(pattern="a/+")],
            rejected=[RejectedTopic(pattern="secret/#", reason="permission_denied")],
            retained=[RetainedEvent(topic="a/b", eventId="e1", payload="val")],
        )
        data = r.model_dump(by_alias=True, mode="json")
        wrapped = ServerResult.model_validate(data)
        parsed = wrapped.root
        assert isinstance(parsed, EventSubscribeResult)
        assert len(parsed.subscribed) == 1
        assert parsed.subscribed[0].pattern == "a/+"
        assert len(parsed.rejected) == 1
        assert parsed.rejected[0].pattern == "secret/#"
        assert parsed.rejected[0].reason == "permission_denied"
        assert len(parsed.retained) == 1
        assert parsed.retained[0].topic == "a/b"
        assert parsed.retained[0].event_id == "e1"
        assert parsed.retained[0].payload == "val"

    def test_unsubscribe_result(self):
        r = EventUnsubscribeResult(unsubscribed=["a/+", "b/#"])
        data = r.model_dump(by_alias=True, mode="json")
        wrapped = ServerResult.model_validate(data)
        parsed = wrapped.root
        assert isinstance(parsed, EventUnsubscribeResult)
        assert parsed.unsubscribed == ["a/+", "b/#"]

    def test_list_result(self):
        r = EventListResult(
            topics=[
                EventTopicDescriptor(pattern="x/y", description="desc"),
            ]
        )
        data = r.model_dump(by_alias=True, mode="json")
        wrapped = ServerResult.model_validate(data)
        parsed = wrapped.root
        assert isinstance(parsed, EventListResult)
        assert len(parsed.topics) == 1
        assert parsed.topics[0].pattern == "x/y"
        assert parsed.topics[0].description == "desc"


class TestInvalidEventEffect:
    def test_invalid_type_rejected(self):
        """EventEffect with an invalid type literal should be rejected by Pydantic."""
        with pytest.raises(ValidationError):
            EventEffect(type="bogus_effect")

    def test_invalid_priority_rejected(self):
        """EventEffect with an invalid priority literal should be rejected."""
        with pytest.raises(ValidationError):
            EventEffect(type="inject_context", priority="super_duper")


class TestInvalidEventParams:
    def test_missing_topic_rejected(self):
        """EventParams missing required 'topic' field should fail validation."""
        with pytest.raises(ValidationError):
            EventParams(eventId="e1", payload="x")

    def test_missing_event_id_rejected(self):
        """EventParams missing required 'event_id' field should fail validation."""
        with pytest.raises(ValidationError):
            EventParams(topic="a/b", payload="x")

    def test_missing_payload_rejected(self):
        """EventParams missing required 'payload' field should fail validation."""
        with pytest.raises(ValidationError):
            EventParams(topic="a/b", eventId="e1")


# ---------------------------------------------------------------------------
# Coverage tests for event handlers, capability detection, and edge cases
# ---------------------------------------------------------------------------

_registry = SubscriptionRegistry()
_retained_store = RetainedValueStore()


async def _on_subscribe_events(
    ctx: RequestContext[ServerSession, Any],
    params: EventSubscribeParams,
) -> EventSubscribeResult:
    subscribed = []
    for pattern in params.topics:
        await _registry.add("test-session", pattern)
        subscribed.append(SubscribedTopic(pattern=pattern))
    return EventSubscribeResult(subscribed=subscribed)


async def _on_unsubscribe_events(
    ctx: RequestContext[ServerSession, Any],
    params: EventUnsubscribeParams,
) -> EventUnsubscribeResult:
    for pattern in params.topics:
        await _registry.remove("test-session", pattern)
    return EventUnsubscribeResult(unsubscribed=params.topics)


def _create_test_server() -> Server:
    server = Server("test-events-server")

    # Register event handlers via request_handlers dict (keyed by type)
    async def subscribe_handler(req: EventSubscribeRequest):
        ctx = server.request_context
        result = await _on_subscribe_events(ctx, req.root.params if hasattr(req, "root") else req.params)
        return types.ServerResult(result)

    async def unsubscribe_handler(req: EventUnsubscribeRequest):
        ctx = server.request_context
        result = await _on_unsubscribe_events(ctx, req.root.params if hasattr(req, "root") else req.params)
        return types.ServerResult(result)

    server.request_handlers[EventSubscribeRequest] = subscribe_handler
    server.request_handlers[EventUnsubscribeRequest] = unsubscribe_handler
    return server


async def _message_handler(
    message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
) -> None:
    if isinstance(message, Exception):
        raise message


async def _run_server(server_session: ServerSession, server: Server) -> None:
    async for message in server_session.incoming_messages:
        if isinstance(message, Exception):
            raise message
        if isinstance(message, RequestResponder):
            with message:
                req = message.request
                # v1.27.0: request_handlers keyed by type
                handler = server.request_handlers.get(type(req.root))
                if handler:
                    from mcp.server.lowlevel.server import request_ctx

                    token = request_ctx.set(
                        RequestContext(
                            request_id=message.request_id,
                            meta=message.request_meta,
                            session=server_session,
                            lifespan_context={},
                        )
                    )
                    try:
                        result = await handler(req.root)
                        await message.respond(result)
                    finally:
                        request_ctx.reset(token)


@pytest.fixture(autouse=True)
def _reset_event_types_registry():
    """Reset the global registry and store between tests."""
    global _registry, _retained_store  # noqa: PLW0603
    _registry = SubscriptionRegistry()
    _retained_store = RetainedValueStore()
    yield


# -- Finding 6: ULID auto-generation --


@pytest.mark.anyio
async def test_emit_event_auto_generates_event_id():
    """emit_event with event_id=None should auto-generate a non-None event_id."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    server = _create_test_server()
    received_events: list[EventParams] = []

    try:
        async with (
            ServerSession(
                client_to_server_receive,
                server_to_client_send,
                InitializationOptions(
                    server_name="test",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(NotificationOptions(), {}),
                ),
            ) as server_session,
            ClientSession(
                server_to_client_receive,
                client_to_server_send,
                message_handler=_message_handler,
            ) as client_session,
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(_run_server, server_session, server)
            await client_session.initialize()

            async def event_handler(params: EventParams):
                received_events.append(params)

            client_session.set_event_handler(event_handler)
            await client_session.subscribe_events(["test/+"])

            # Emit without explicit event_id
            await server_session.emit_event(
                topic="test/auto-id",
                payload={"auto": True},
            )

            await anyio.sleep(0.1)

            assert len(received_events) == 1
            assert received_events[0].event_id is not None
            assert len(received_events[0].event_id) > 0

            tg.cancel_scope.cancel()
    except (anyio.ClosedResourceError, anyio.EndOfStream):
        pass


# -- Finding 7: on_event() decorator --


@pytest.mark.anyio
async def test_on_event_decorator():
    """The @session.on_event() decorator should work like set_event_handler."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    server = _create_test_server()
    received_events: list[EventParams] = []

    try:
        async with (
            ServerSession(
                client_to_server_receive,
                server_to_client_send,
                InitializationOptions(
                    server_name="test",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(NotificationOptions(), {}),
                ),
            ) as server_session,
            ClientSession(
                server_to_client_receive,
                client_to_server_send,
                message_handler=_message_handler,
            ) as client_session,
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(_run_server, server_session, server)
            await client_session.initialize()

            @client_session.on_event()
            async def handle_event(params: EventParams):
                received_events.append(params)

            await client_session.subscribe_events(["test/+"])

            await server_session.emit_event(
                topic="test/decorator",
                payload="via-decorator",
                event_id="dec-1",
            )

            await anyio.sleep(0.1)

            assert len(received_events) == 1
            assert received_events[0].topic == "test/decorator"
            assert received_events[0].payload == "via-decorator"

            tg.cancel_scope.cancel()
    except (anyio.ClosedResourceError, anyio.EndOfStream):
        pass


# -- Finding 8: _topic_matches_subscriptions with empty subscriptions --


@pytest.mark.anyio
async def test_topic_matches_with_no_subscriptions():
    """When no subscriptions exist, all events should pass through (no filtering)."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    server = _create_test_server()
    received_events: list[EventParams] = []

    try:
        async with (
            ServerSession(
                client_to_server_receive,
                server_to_client_send,
                InitializationOptions(
                    server_name="test",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(NotificationOptions(), {}),
                ),
            ) as server_session,
            ClientSession(
                server_to_client_receive,
                client_to_server_send,
                message_handler=_message_handler,
            ) as client_session,
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(_run_server, server_session, server)
            await client_session.initialize()

            async def event_handler(params: EventParams):
                received_events.append(params)

            # Register handler but do NOT subscribe -- empty subscriptions means pass all
            client_session.set_event_handler(event_handler)

            await server_session.emit_event(
                topic="anything/goes",
                payload="unfiltered",
                event_id="unf-1",
            )

            await anyio.sleep(0.1)

            assert len(received_events) == 1
            assert received_events[0].topic == "anything/goes"

            tg.cancel_scope.cancel()
    except (anyio.ClosedResourceError, anyio.EndOfStream):
        pass


# -- Finding 9: set_event_handler with topic_filter --


@pytest.mark.anyio
async def test_set_event_handler_with_topic_filter():
    """set_event_handler with topic_filter should only pass matching events."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    server = _create_test_server()
    received_events: list[EventParams] = []

    try:
        async with (
            ServerSession(
                client_to_server_receive,
                server_to_client_send,
                InitializationOptions(
                    server_name="test",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(NotificationOptions(), {}),
                ),
            ) as server_session,
            ClientSession(
                server_to_client_receive,
                client_to_server_send,
                message_handler=_message_handler,
            ) as client_session,
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(_run_server, server_session, server)
            await client_session.initialize()

            async def event_handler(params: EventParams):
                received_events.append(params)

            # Filter to only "test/specific" topic
            client_session.set_event_handler(event_handler, topic_filter="test/specific")

            # Don't subscribe so subscription filtering doesn't interfere
            # (empty subscriptions = pass all through subscription check)

            await server_session.emit_event(
                topic="test/specific",
                payload="match",
                event_id="tf-1",
            )
            await server_session.emit_event(
                topic="test/other",
                payload="no-match",
                event_id="tf-2",
            )

            await anyio.sleep(0.1)

            assert len(received_events) == 1
            assert received_events[0].topic == "test/specific"
            assert received_events[0].payload == "match"

            tg.cancel_scope.cancel()
    except (anyio.ClosedResourceError, anyio.EndOfStream):
        pass


# -- Finding 10: _handle_event with no handler registered --


@pytest.mark.anyio
async def test_handle_event_with_no_handler():
    """Receiving an event before any handler is registered should not crash."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    server = _create_test_server()

    try:
        async with (
            ServerSession(
                client_to_server_receive,
                server_to_client_send,
                InitializationOptions(
                    server_name="test",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(NotificationOptions(), {}),
                ),
            ) as server_session,
            ClientSession(
                server_to_client_receive,
                client_to_server_send,
                message_handler=_message_handler,
            ) as client_session,
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(_run_server, server_session, server)
            await client_session.initialize()

            # Do NOT register any event handler

            # Server emits -- should not crash
            await server_session.emit_event(
                topic="test/no-handler",
                payload="ignored",
                event_id="nh-1",
            )

            await anyio.sleep(0.1)
            # If we get here without exception, the test passes

            tg.cancel_scope.cancel()
    except (anyio.ClosedResourceError, anyio.EndOfStream):
        pass


# -- Finding 11: Server capability detection --


def test_events_capability_present_with_handler():
    """Events capability should be present when event handlers are registered."""
    server = _create_test_server()
    caps = server.get_capabilities(NotificationOptions(), {})
    assert caps.events is not None


def test_events_capability_absent_without_handler():
    """Events capability should be None when no event handlers are registered."""
    server = Server("no-events-server")
    caps = server.get_capabilities(NotificationOptions(), {})
    assert caps.events is None


# -- Finding 12: _is_expired with malformed date --


@pytest.mark.anyio
async def test_is_expired_with_malformed_date():
    """Malformed expires_at should return False (event not considered expired)."""
    store = RetainedValueStore()
    event = RetainedEvent(topic="a/b", eventId="e1", payload="val")
    await store.set("a/b", event, expires_at="not-a-date")
    # Should return the event (not expired due to malformed date)
    result = await store.get("a/b")
    assert result == event


@pytest.mark.anyio
async def test_is_expired_with_malformed_date_in_get_matching():
    """Malformed expires_at in get_matching should treat event as non-expired."""
    store = RetainedValueStore()
    event = RetainedEvent(topic="a/b", eventId="e1", payload="val")
    await store.set("a/b", event, expires_at="garbage-timestamp")
    matching = await store.get_matching("a/+")
    assert len(matching) == 1
    assert matching[0].event_id == "e1"


# -- Finding 13: emit_event optional parameters roundtrip --


@pytest.mark.anyio
async def test_emit_event_optional_parameters_roundtrip():
    """All optional parameters (source, correlation_id, requested_effects, expires_at)
    should survive the server->client roundtrip."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    server = _create_test_server()
    received_events: list[EventParams] = []

    try:
        async with (
            ServerSession(
                client_to_server_receive,
                server_to_client_send,
                InitializationOptions(
                    server_name="test",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(NotificationOptions(), {}),
                ),
            ) as server_session,
            ClientSession(
                server_to_client_receive,
                client_to_server_send,
                message_handler=_message_handler,
            ) as client_session,
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(_run_server, server_session, server)
            await client_session.initialize()

            async def event_handler(params: EventParams):
                received_events.append(params)

            client_session.set_event_handler(event_handler)

            future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

            await server_session.emit_event(
                topic="test/full",
                payload={"detail": "value"},
                event_id="full-1",
                source="test-source",
                correlation_id="corr-123",
                requested_effects=[],
                expires_at=future,
            )

            await anyio.sleep(0.1)

            assert len(received_events) == 1
            evt = received_events[0]
            assert evt.topic == "test/full"
            assert evt.payload == {"detail": "value"}
            assert evt.event_id == "full-1"
            assert evt.source == "test-source"
            assert evt.correlation_id == "corr-123"
            assert evt.requested_effects == []
            assert evt.expires_at == future

            tg.cancel_scope.cancel()
    except (anyio.ClosedResourceError, anyio.EndOfStream):
        pass


# -- Finding 2 coverage: timestamp auto-set --


@pytest.mark.anyio
async def test_emit_event_auto_sets_timestamp():
    """emit_event should auto-set timestamp when not provided."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    server = _create_test_server()
    received_events: list[EventParams] = []

    try:
        async with (
            ServerSession(
                client_to_server_receive,
                server_to_client_send,
                InitializationOptions(
                    server_name="test",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(NotificationOptions(), {}),
                ),
            ) as server_session,
            ClientSession(
                server_to_client_receive,
                client_to_server_send,
                message_handler=_message_handler,
            ) as client_session,
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(_run_server, server_session, server)
            await client_session.initialize()

            async def event_handler(params: EventParams):
                received_events.append(params)

            client_session.set_event_handler(event_handler)

            before = datetime.now(timezone.utc)

            await server_session.emit_event(
                topic="test/ts",
                payload="timestamp-test",
                event_id="ts-1",
            )

            await anyio.sleep(0.1)

            assert len(received_events) == 1
            assert received_events[0].timestamp is not None
            ts = datetime.fromisoformat(received_events[0].timestamp)
            assert ts >= before
            assert ts <= datetime.now(timezone.utc)

            tg.cancel_scope.cancel()
    except (anyio.ClosedResourceError, anyio.EndOfStream):
        pass
