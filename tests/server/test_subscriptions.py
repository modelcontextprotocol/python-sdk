"""Tests for `subscriptions/listen` serving (mcp.server.subscriptions)."""

from typing import Any, cast

import anyio
import pytest
from mcp_types import (
    INVALID_REQUEST,
    PromptListChangedNotification,
    RequestId,
    ResourceListChangedNotification,
    ResourceUpdatedNotification,
    ServerNotification,
    SubscriptionFilter,
    SubscriptionsAcknowledgedNotification,
    SubscriptionsListenRequestParams,
    SubscriptionsListenResult,
    ToolListChangedNotification,
)

from mcp.server.context import ServerRequestContext
from mcp.server.session import ServerSession
from mcp.server.subscriptions import (
    SUBSCRIPTION_ID_META_KEY,
    InMemoryEventBus,
    ListenHandler,
    PromptsListChanged,
    ResourcesListChanged,
    ResourceUpdated,
    ServerEvent,
    ToolsListChanged,
)
from mcp.shared.exceptions import MCPError


class _RecordingSession:
    """Stands in for `ServerSession`: records sent notifications and wakes waiters."""

    def __init__(self) -> None:
        self.sent: list[tuple[ServerNotification, RequestId | None]] = []
        self._arrival = anyio.Event()

    async def send_notification(
        self, notification: ServerNotification, related_request_id: RequestId | None = None
    ) -> None:
        self.sent.append((notification, related_request_id))
        self._arrival.set()
        self._arrival = anyio.Event()

    async def wait_for(self, count: int) -> None:
        with anyio.fail_after(5):
            while len(self.sent) < count:
                await self._arrival.wait()


def _ctx(session: _RecordingSession, request_id: RequestId | None = 7) -> ServerRequestContext[Any, Any]:
    return ServerRequestContext(
        session=cast(ServerSession, session),
        lifespan_context={},
        protocol_version="2026-07-28",
        method="subscriptions/listen",
        request_id=request_id,
    )


def _params(**fields: Any) -> SubscriptionsListenRequestParams:
    return SubscriptionsListenRequestParams(notifications=SubscriptionFilter(**fields))


class _SpyBus(InMemoryEventBus):
    """Counts unsubscribe calls so tests can assert stream cleanup."""

    def __init__(self) -> None:
        super().__init__()
        self.unsubscribed = 0

    def subscribe(self, listener: Any) -> Any:
        unsubscribe = super().subscribe(listener)

        def counting_unsubscribe() -> None:
            self.unsubscribed += 1
            unsubscribe()

        return counting_unsubscribe


def test_in_memory_bus_fans_out_until_unsubscribed() -> None:
    bus = InMemoryEventBus()
    seen_a: list[ServerEvent] = []
    seen_b: list[ServerEvent] = []
    unsubscribe_a = bus.subscribe(seen_a.append)
    bus.subscribe(seen_b.append)

    bus.publish(ToolsListChanged())
    assert seen_a == [ToolsListChanged()]
    assert seen_b == [ToolsListChanged()]

    unsubscribe_a()
    unsubscribe_a()  # idempotent
    bus.publish(PromptsListChanged())
    assert seen_a == [ToolsListChanged()]
    assert seen_b == [ToolsListChanged(), PromptsListChanged()]


@pytest.mark.anyio
async def test_ack_first_honored_subset_and_stamped_graceful_result() -> None:
    bus = _SpyBus()
    handler = ListenHandler(bus)
    session = _RecordingSession()
    results: list[SubscriptionsListenResult] = []

    async with anyio.create_task_group() as tg:

        async def run() -> None:
            results.append(
                await handler(
                    _ctx(session),
                    _params(tools_list_changed=True, prompts_list_changed=False, resource_subscriptions=["r://a"]),
                )
            )

        tg.start_soon(run)
        await session.wait_for(1)

        ack, related = session.sent[0]
        assert isinstance(ack, SubscriptionsAcknowledgedNotification)
        assert related == 7
        # Honored subset: requested-false and absent kinds are omitted, not echoed.
        assert ack.params.notifications == SubscriptionFilter(tools_list_changed=True, resource_subscriptions=["r://a"])
        assert ack.params.meta == {SUBSCRIPTION_ID_META_KEY: 7}

        bus.publish(ToolsListChanged())
        await session.wait_for(2)
        event, related = session.sent[1]
        assert isinstance(event, ToolListChangedNotification)
        assert related == 7
        assert event.params is not None and event.params.meta == {SUBSCRIPTION_ID_META_KEY: 7}

        handler.close()

    assert results[0].meta == {SUBSCRIPTION_ID_META_KEY: 7}
    assert bus.unsubscribed == 1  # the stream unsubscribed on the way out


@pytest.mark.anyio
async def test_only_requested_event_kinds_are_delivered() -> None:
    bus = InMemoryEventBus()
    handler = ListenHandler(bus)
    session = _RecordingSession()

    async with anyio.create_task_group() as tg:

        async def run() -> None:
            await handler(
                _ctx(session),
                _params(prompts_list_changed=True, resources_list_changed=True, resource_subscriptions=["r://a"]),
            )

        tg.start_soon(run)
        await session.wait_for(1)

        bus.publish(ToolsListChanged())  # not requested
        bus.publish(ResourceUpdated(uri="r://other"))  # URI not subscribed
        bus.publish(PromptsListChanged())
        bus.publish(ResourcesListChanged())
        bus.publish(ResourceUpdated(uri="r://a"))
        await session.wait_for(4)
        handler.close()

    delivered = [notification for notification, _ in session.sent[1:]]
    assert isinstance(delivered[0], PromptListChangedNotification)
    assert isinstance(delivered[1], ResourceListChangedNotification)
    assert isinstance(delivered[2], ResourceUpdatedNotification)
    assert delivered[2].params.uri == "r://a"
    assert delivered[2].params.meta == {SUBSCRIPTION_ID_META_KEY: 7}
    assert len(delivered) == 3


@pytest.mark.anyio
async def test_empty_filter_honors_nothing_and_delivers_nothing() -> None:
    bus = InMemoryEventBus()
    handler = ListenHandler(bus)
    session = _RecordingSession()

    async with anyio.create_task_group() as tg:

        async def run() -> None:
            await handler(_ctx(session), _params(tools_list_changed=False, resource_subscriptions=[]))

        tg.start_soon(run)
        await session.wait_for(1)

        ack, _ = session.sent[0]
        assert isinstance(ack, SubscriptionsAcknowledgedNotification)
        assert ack.params.notifications == SubscriptionFilter()

        for event in (ToolsListChanged(), PromptsListChanged(), ResourcesListChanged(), ResourceUpdated(uri="r://a")):
            bus.publish(event)
        handler.close()

    assert len(session.sent) == 1  # the ack only


@pytest.mark.anyio
async def test_publish_after_close_is_dropped() -> None:
    bus = InMemoryEventBus()
    handler = ListenHandler(bus)
    session = _RecordingSession()

    async with anyio.create_task_group() as tg:

        async def run() -> None:
            await handler(_ctx(session), _params(tools_list_changed=True))

        tg.start_soon(run)
        await session.wait_for(1)

        handler.close()
        # The handler task has not resumed yet, so the listener is still
        # subscribed but its stream is closed: the event is dropped.
        bus.publish(ToolsListChanged())

    assert len(session.sent) == 1


@pytest.mark.anyio
async def test_listen_requires_a_request_id() -> None:
    handler = ListenHandler(InMemoryEventBus())

    with pytest.raises(MCPError) as exc_info:
        await handler(_ctx(_RecordingSession(), request_id=None), _params())
    assert exc_info.value.error.code == INVALID_REQUEST


def test_close_without_open_streams_is_a_no_op() -> None:
    ListenHandler(InMemoryEventBus()).close()
