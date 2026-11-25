"""Tests for `subscriptions/listen` serving (mcp.server.subscriptions)."""

from collections.abc import Callable
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
    InMemorySubscriptionBus,
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


class _SpyBus(InMemorySubscriptionBus):
    """Counts unsubscribe calls so tests can assert stream cleanup."""

    def __init__(self) -> None:
        super().__init__()
        self.unsubscribed = 0

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        unsubscribe = super().subscribe(listener)

        def counting_unsubscribe() -> None:
            self.unsubscribed += 1
            unsubscribe()

        return counting_unsubscribe


@pytest.mark.anyio
async def test_in_memory_bus_fans_out_until_unsubscribed() -> None:
    """SDK-defined bus contract: fan-out to all listeners; unsubscribe is idempotent."""
    bus = InMemorySubscriptionBus()
    seen_a: list[ServerEvent] = []
    seen_b: list[ServerEvent] = []
    unsubscribe_a = bus.subscribe(seen_a.append)
    bus.subscribe(seen_b.append)

    await bus.publish(ToolsListChanged())
    assert seen_a == [ToolsListChanged()]
    assert seen_b == [ToolsListChanged()]

    unsubscribe_a()
    unsubscribe_a()  # idempotent
    await bus.publish(PromptsListChanged())
    assert seen_a == [ToolsListChanged()]
    assert seen_b == [ToolsListChanged(), PromptsListChanged()]


@pytest.mark.anyio
async def test_in_memory_bus_keeps_equal_callables_distinct() -> None:
    """SDK-defined: registering the same callable twice yields two registrations,
    and each unsubscribe detaches exactly one (bound methods compare equal)."""
    bus = InMemorySubscriptionBus()
    seen: list[ServerEvent] = []
    first = bus.subscribe(seen.append)
    bus.subscribe(seen.append)

    await bus.publish(ToolsListChanged())
    assert len(seen) == 2

    first()
    await bus.publish(ToolsListChanged())
    assert len(seen) == 3


@pytest.mark.anyio
async def test_ack_first_honored_subset_and_stamped_graceful_result() -> None:
    """Spec-mandated: the ack is the first frame, echoes the honored subset, and
    every frame (graceful result included) carries the subscription-id tag."""
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

        await bus.publish(ToolsListChanged())
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
    """Spec-mandated: the server never sends a notification type (or resource URI)
    the client did not request on this stream."""
    bus = InMemorySubscriptionBus()
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

        await bus.publish(ToolsListChanged())  # not requested
        await bus.publish(ResourceUpdated(uri="r://other"))  # URI not subscribed
        await bus.publish(PromptsListChanged())
        await bus.publish(ResourcesListChanged())
        await bus.publish(ResourceUpdated(uri="r://a"))
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
    """SDK-defined: falsy flags and an empty URI list are dropped from the ack
    rather than echoed, and such a stream delivers nothing."""
    bus = InMemorySubscriptionBus()
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
            await bus.publish(event)
        handler.close()

    assert len(session.sent) == 1  # the ack only


@pytest.mark.anyio
async def test_publish_after_close_is_dropped() -> None:
    """SDK-defined: an event racing `close()` while the stream unwinds is dropped."""
    bus = InMemorySubscriptionBus()
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
        await bus.publish(ToolsListChanged())

    assert len(session.sent) == 1


@pytest.mark.anyio
async def test_event_published_during_ack_send_is_delivered_after_the_ack() -> None:
    """SDK-defined: the stream subscribes before sending the ack, so an event
    published while the ack write is suspended is buffered and delivered after
    it - never lost, and never ahead of the ack frame."""
    bus = InMemorySubscriptionBus()
    handler = ListenHandler(bus)

    class _PublishDuringAck(_RecordingSession):
        async def send_notification(
            self, notification: ServerNotification, related_request_id: RequestId | None = None
        ) -> None:
            if not self.sent:
                # Publish while the handler is still inside the ack send.
                await bus.publish(ToolsListChanged())
            await super().send_notification(notification, related_request_id)

    session = _PublishDuringAck()

    async with anyio.create_task_group() as tg:

        async def run() -> None:
            await handler(_ctx(session), _params(tools_list_changed=True))

        tg.start_soon(run)
        await session.wait_for(2)
        handler.close()

    assert isinstance(session.sent[0][0], SubscriptionsAcknowledgedNotification)
    assert isinstance(session.sent[1][0], ToolListChangedNotification)


@pytest.mark.anyio
async def test_listen_requires_a_request_id() -> None:
    """SDK-defined: a context without a request id cannot open a stream."""
    handler = ListenHandler(InMemorySubscriptionBus())

    with pytest.raises(MCPError) as exc_info:
        await handler(_ctx(_RecordingSession(), request_id=None), _params())
    assert exc_info.value.error.code == INVALID_REQUEST


def test_close_without_open_streams_is_a_no_op() -> None:
    """SDK-defined: `close()` with nothing open does nothing."""
    ListenHandler(InMemorySubscriptionBus()).close()


@pytest.mark.anyio
async def test_raising_listener_is_isolated_from_others() -> None:
    """SDK-defined: one raising listener is logged and skipped; later listeners
    and the publishing handler are unaffected."""
    bus = InMemorySubscriptionBus()

    def bad(event: ServerEvent) -> None:
        raise RuntimeError("boom")

    seen: list[ServerEvent] = []
    bus.subscribe(bad)
    bus.subscribe(seen.append)

    await bus.publish(ToolsListChanged())
    assert seen == [ToolsListChanged()]


@pytest.mark.anyio
async def test_raising_unsubscribe_does_not_skip_stream_cleanup() -> None:
    """SDK-defined: a custom bus whose unsubscribe callable raises is logged
    and isolated - the stream still releases its subscription slot, closes its
    buffers, and returns the graceful result."""

    class _RaisingUnsubscribeBus(InMemorySubscriptionBus):
        def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
            super().subscribe(listener)

            def unsubscribe() -> None:
                raise RuntimeError("boom")

            return unsubscribe

    handler = ListenHandler(_RaisingUnsubscribeBus(), max_subscriptions=1)
    session = _RecordingSession()
    results: list[SubscriptionsListenResult] = []

    async with anyio.create_task_group() as tg:

        async def run() -> None:
            results.append(await handler(_ctx(session), _params(tools_list_changed=True)))

        tg.start_soon(run)
        await session.wait_for(1)
        handler.close()

    assert results[0].meta == {SUBSCRIPTION_ID_META_KEY: 7}  # the graceful result still returned

    # The slot was released despite the raising unsubscribe: a second listen
    # is accepted at the cap of one.
    late_session = _RecordingSession()
    late_results: list[SubscriptionsListenResult] = []

    async with anyio.create_task_group() as tg:

        async def run_late() -> None:
            late_results.append(await handler(_ctx(late_session, request_id=8), _params(tools_list_changed=True)))

        tg.start_soon(run_late)
        await late_session.wait_for(1)
        handler.close()

    assert late_results[0].meta == {SUBSCRIPTION_ID_META_KEY: 8}


@pytest.mark.anyio
async def test_subscription_limit_rejects_further_streams_pre_ack() -> None:
    """SDK-defined cap (mirrors the TypeScript SDK): past `max_subscriptions`,
    a listen request is rejected before any ack frame."""
    handler = ListenHandler(InMemorySubscriptionBus(), max_subscriptions=1)
    session = _RecordingSession()

    async with anyio.create_task_group() as tg:

        async def run() -> None:
            await handler(_ctx(session), _params(tools_list_changed=True))

        tg.start_soon(run)
        await session.wait_for(1)

        rejected_session = _RecordingSession()
        with pytest.raises(MCPError) as exc_info:
            await handler(_ctx(rejected_session, request_id=8), _params())
        assert exc_info.value.error.message == "Subscription limit reached"
        assert rejected_session.sent == []

        handler.close()


class _GatedSession(_RecordingSession):
    """Lets the ack through, then wedges event sends until released - a client
    that stopped reading the transport."""

    def __init__(self) -> None:
        super().__init__()
        self.wedged = anyio.Event()
        self.release = anyio.Event()

    async def send_notification(
        self, notification: ServerNotification, related_request_id: RequestId | None = None
    ) -> None:
        if self.sent:  # the ack is the first frame; only event sends wedge
            self.wedged.set()
            await self.release.wait()
        await super().send_notification(notification, related_request_id)


@pytest.mark.anyio
async def test_backlog_overflow_ends_the_stream_and_frees_its_slot() -> None:
    """SDK-defined: a stream whose client stopped reading is ended at
    `max_buffered_events` rather than buffering forever. The subscription slot
    frees at overflow time - the stream's own cleanup may be wedged in a
    transport write nothing can wake - and the backlog still drains into the
    stamped graceful result once that write completes."""
    bus = InMemorySubscriptionBus()
    handler = ListenHandler(bus, max_subscriptions=1, max_buffered_events=1)
    session = _GatedSession()
    results: list[SubscriptionsListenResult] = []
    late_session = _RecordingSession()
    late_results: list[SubscriptionsListenResult] = []

    async with anyio.create_task_group() as tg:

        async def run() -> None:
            results.append(await handler(_ctx(session), _params(tools_list_changed=True)))

        tg.start_soon(run)
        await session.wait_for(1)

        await bus.publish(ToolsListChanged())  # consumed, then wedged mid-send
        with anyio.fail_after(5):
            await session.wedged.wait()
        await bus.publish(ToolsListChanged())  # fills the one-slot buffer
        await bus.publish(ToolsListChanged())  # overflows: the stream is ended

        async def run_late() -> None:
            late_results.append(await handler(_ctx(late_session, request_id=8), _params(tools_list_changed=True)))

        # The ended stream's slot is free immediately - a new listen does not
        # wait for the wedged write to die with its connection.
        tg.start_soon(run_late)
        await late_session.wait_for(1)

        session.release.set()
        handler.close()

    delivered = [notification for notification, _ in session.sent[1:]]
    assert len(delivered) == 2  # the wedged event and the buffered one still drained
    assert results[0].meta == {SUBSCRIPTION_ID_META_KEY: 7}
    assert late_results[0].meta == {SUBSCRIPTION_ID_META_KEY: 8}


@pytest.mark.anyio
async def test_same_task_publish_burst_does_not_overflow_a_healthy_stream() -> None:
    """SDK-defined: `publish` ends with a checkpoint, so a burst of events from
    one task (no yields of its own) lets a reading stream drain between
    publishes instead of deterministically overflowing the buffer."""
    bus = InMemorySubscriptionBus()
    handler = ListenHandler(bus, max_buffered_events=99)
    session = _RecordingSession()

    async with anyio.create_task_group() as tg:

        async def run() -> None:
            await handler(_ctx(session), _params(tools_list_changed=True))

        tg.start_soon(run)
        await session.wait_for(1)

        for _ in range(100):
            await bus.publish(ToolsListChanged())
        await session.wait_for(101)
        handler.close()

    assert len(session.sent) == 101  # the ack plus every event in the burst
