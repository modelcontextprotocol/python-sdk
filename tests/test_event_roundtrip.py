"""End-to-end tests for events: server emit -> client receive over in-memory transport."""

from __future__ import annotations

import asyncio
from typing import Any

import anyio
import pytest

from mcp import types
from mcp.client.session import ClientSession
from mcp.server.lowlevel.server import Server, request_ctx
from mcp.shared.context import RequestContext
from mcp.server.events import RetainedValueStore, SubscriptionRegistry
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
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
    SubscribedTopic,
)


# Shared registry and store for the test server
_registry = SubscriptionRegistry()
_retained_store = RetainedValueStore()
_topic_descriptors: list[EventTopicDescriptor] = [
    EventTopicDescriptor(pattern="test/+", description="Test topic"),
    EventTopicDescriptor(pattern="retained/value", description="Retained", retained=True),
]


async def _on_subscribe_events(
    ctx: RequestContext[ServerSession, Any],
    params: EventSubscribeParams,
) -> EventSubscribeResult:
    subscribed = []
    for pattern in params.topics:
        await _registry.add("test-session", pattern)
        subscribed.append(SubscribedTopic(pattern=pattern))

    # Gather retained values
    retained_events: list[RetainedEvent] = []
    for pattern in params.topics:
        retained_events.extend(await _retained_store.get_matching(pattern))

    return EventSubscribeResult(
        subscribed=subscribed,
        retained=retained_events,
    )


async def _on_unsubscribe_events(
    ctx: RequestContext[ServerSession, Any],
    params: EventUnsubscribeParams,
) -> EventUnsubscribeResult:
    for pattern in params.topics:
        await _registry.remove("test-session", pattern)
    return EventUnsubscribeResult(unsubscribed=params.topics)


async def _on_list_events(
    ctx: RequestContext[ServerSession, Any],
    params: types.RequestParams | None,
) -> EventListResult:
    return EventListResult(topics=_topic_descriptors)


def _create_test_server() -> Server:
    server = Server("test-events-server")

    async def subscribe_handler(req: EventSubscribeRequest):
        ctx = request_ctx.get()
        result = await _on_subscribe_events(ctx, req.params)
        return types.ServerResult(result)

    async def unsubscribe_handler(req: EventUnsubscribeRequest):
        ctx = request_ctx.get()
        result = await _on_unsubscribe_events(ctx, req.params)
        return types.ServerResult(result)

    async def list_handler(req: EventListRequest):
        ctx = request_ctx.get()
        result = await _on_list_events(ctx, req.params)
        return types.ServerResult(result)

    server.request_handlers[EventSubscribeRequest] = subscribe_handler
    server.request_handlers[EventUnsubscribeRequest] = unsubscribe_handler
    server.request_handlers[EventListRequest] = list_handler
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
                handler = server.request_handlers.get(type(req.root))
                if handler:
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
async def reset_registry():
    """Reset the global registry and store between tests."""
    global _registry, _retained_store
    _registry = SubscriptionRegistry()
    _retained_store = RetainedValueStore()
    yield


@pytest.mark.anyio
async def test_emit_event_received_by_client():
    """Server emits an event, client receives it via notification handler."""
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

            result = await client_session.initialize()
            assert result.capabilities.events is not None

            # Register event handler
            async def event_handler(params: EventParams):
                received_events.append(params)

            client_session.set_event_handler(event_handler)

            # Subscribe
            sub_result = await client_session.subscribe_events(["test/+"])
            assert len(sub_result.subscribed) == 1

            # Server emits
            await server_session.emit_event(
                topic="test/hello",
                payload={"message": "world"},
                event_id="evt-1",
            )

            # Give the notification time to propagate
            await anyio.sleep(0.1)

            assert len(received_events) == 1
            assert received_events[0].topic == "test/hello"
            assert received_events[0].payload == {"message": "world"}
            assert received_events[0].event_id == "evt-1"

            tg.cancel_scope.cancel()
    except (anyio.ClosedResourceError, anyio.EndOfStream):
        pass


@pytest.mark.anyio
async def test_subscribe_receives_retained_values():
    """Subscribing delivers retained values inline in the subscribe result."""
    # Pre-populate a retained value
    await _retained_store.set(
        "retained/value",
        RetainedEvent(topic="retained/value", eventId="ret-1", payload="cached"),
    )

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

            sub_result = await client_session.subscribe_events(["retained/+"])
            assert len(sub_result.retained) == 1
            assert sub_result.retained[0].topic == "retained/value"
            assert sub_result.retained[0].payload == "cached"

            tg.cancel_scope.cancel()
    except (anyio.ClosedResourceError, anyio.EndOfStream):
        pass


@pytest.mark.anyio
async def test_unsubscribe_stops_matching():
    """After unsubscribing, the registry no longer matches the pattern."""
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

            # Subscribe then unsubscribe
            await client_session.subscribe_events(["test/+"])
            unsub = await client_session.unsubscribe_events(["test/+"])
            assert unsub.unsubscribed == ["test/+"]

            # Registry should no longer match
            matches = await _registry.match("test/hello")
            assert matches == set()

            tg.cancel_scope.cancel()
    except (anyio.ClosedResourceError, anyio.EndOfStream):
        pass


@pytest.mark.anyio
async def test_client_subscription_tracking_drops_unsubscribed():
    """Client-side subscription tracking drops events for unsubscribed topics."""
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

            # Subscribe to test/+ only
            await client_session.subscribe_events(["test/+"])

            # Server emits to a topic that matches the subscription
            await server_session.emit_event(
                topic="test/match",
                payload="yes",
                event_id="evt-match",
            )

            # Server emits to a topic that does NOT match
            await server_session.emit_event(
                topic="other/topic",
                payload="no",
                event_id="evt-other",
            )

            await anyio.sleep(0.1)

            # Only the matching event should be received
            assert len(received_events) == 1
            assert received_events[0].topic == "test/match"
            assert received_events[0].payload == "yes"
            assert received_events[0].event_id == "evt-match"

            tg.cancel_scope.cancel()
    except (anyio.ClosedResourceError, anyio.EndOfStream):
        pass


@pytest.mark.anyio
async def test_list_events():
    """Client can list available event topics from the server."""
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

            result = await client_session.list_events()
            assert len(result.topics) == 2
            patterns = {t.pattern for t in result.topics}
            assert "test/+" in patterns
            assert "retained/value" in patterns

            # Verify descriptions and retained flags
            by_pattern = {t.pattern: t for t in result.topics}
            assert by_pattern["test/+"].description == "Test topic"
            assert by_pattern["test/+"].retained is False
            assert by_pattern["retained/value"].description == "Retained"
            assert by_pattern["retained/value"].retained is True

            tg.cancel_scope.cancel()
    except (anyio.ClosedResourceError, anyio.EndOfStream):
        pass


# -- Declared topic patterns for rejection flow test --
_declared_patterns = {"test/+", "retained/value"}


async def _on_subscribe_events_with_rejection(
    ctx: RequestContext[ServerSession, Any],
    params: EventSubscribeParams,
) -> EventSubscribeResult:
    """Subscribe handler that rejects undeclared topic patterns."""
    subscribed = []
    rejected = []
    for pattern in params.topics:
        if pattern in _declared_patterns:
            await _registry.add("test-session", pattern)
            subscribed.append(SubscribedTopic(pattern=pattern))
        else:
            rejected.append(RejectedTopic(pattern=pattern, reason="unknown_topic"))

    return EventSubscribeResult(
        subscribed=subscribed,
        rejected=rejected,
    )


def _create_rejecting_server() -> Server:
    server = Server("test-rejecting-server")

    async def subscribe_handler(req: EventSubscribeRequest):
        ctx = request_ctx.get()
        result = await _on_subscribe_events_with_rejection(ctx, req.params)
        return types.ServerResult(result)

    async def unsubscribe_handler(req: EventUnsubscribeRequest):
        ctx = request_ctx.get()
        result = await _on_unsubscribe_events(ctx, req.params)
        return types.ServerResult(result)

    async def list_handler(req: EventListRequest):
        ctx = request_ctx.get()
        result = await _on_list_events(ctx, req.params)
        return types.ServerResult(result)

    server.request_handlers[EventSubscribeRequest] = subscribe_handler
    server.request_handlers[EventUnsubscribeRequest] = unsubscribe_handler
    server.request_handlers[EventListRequest] = list_handler
    return server


@pytest.mark.anyio
async def test_subscribe_rejects_undeclared_topic():
    """Subscribing to an undeclared topic returns it in rejected list."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    server = _create_rejecting_server()

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

            # Subscribe to one declared and one undeclared topic
            sub_result = await client_session.subscribe_events(["test/+", "secret/stuff"])
            assert len(sub_result.subscribed) == 1
            assert sub_result.subscribed[0].pattern == "test/+"
            assert len(sub_result.rejected) == 1
            assert sub_result.rejected[0].pattern == "secret/stuff"
            assert sub_result.rejected[0].reason == "unknown_topic"

            tg.cancel_scope.cancel()
    except (anyio.ClosedResourceError, anyio.EndOfStream):
        pass
