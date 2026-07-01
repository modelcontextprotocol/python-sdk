"""Behavioral tests for the client-side `subscriptions/listen` driver.

Everything runs through the public API (`Client.listen`) against in-process
servers, per the repo's mirror rule for `src/mcp/client/subscriptions.py`.
Wire-shape assertions (subscription-id tagging, ack-first ordering) live in
the interaction suite; these tests pin the driver's contract.
"""

from itertools import count
from typing import Any

import anyio
import mcp_types as types
import pytest
from mcp_types import SubscriptionFilter

import mcp.client.subscriptions as subscriptions_module
from mcp import Client, MCPError
from mcp.client.session import ClientSession
from mcp.client.subscriptions import (
    ListenNotSupportedError,
    PromptsListChanged,
    ResourcesListChanged,
    ResourceUpdated,
    Subscription,
    SubscriptionLost,
    ToolsListChanged,
    listen,
)
from mcp.server import Server, ServerRequestContext
from mcp.server.subscriptions import (
    SUBSCRIPTION_ID_META_KEY,
    InMemorySubscriptionBus,
    ListenHandler,
)
from mcp.shared.direct_dispatcher import create_direct_dispatcher_pair
from mcp.shared.dispatcher import CallOptions

pytestmark = pytest.mark.anyio


def _bus_server(bus: InMemorySubscriptionBus, *, max_subscriptions: int | None = None) -> Server[Any]:
    """A lowlevel server whose only feature is serving listen streams from `bus`."""
    handler = (
        ListenHandler(bus) if max_subscriptions is None else ListenHandler(bus, max_subscriptions=max_subscriptions)
    )
    return Server("subs", on_subscriptions_listen=handler)


async def _ack(ctx: ServerRequestContext[Any, Any], honored: SubscriptionFilter) -> dict[str, Any]:
    """Send a hand-rolled ack for a scripted listen handler; returns the stamped meta."""
    assert ctx.request_id is not None
    meta: dict[str, Any] = {SUBSCRIPTION_ID_META_KEY: ctx.request_id}
    await ctx.session.send_notification(
        types.SubscriptionsAcknowledgedNotification(
            params=types.SubscriptionsAcknowledgedNotificationParams(notifications=honored, _meta=meta)
        ),
        related_request_id=ctx.request_id,
    )
    return meta


async def test_listen_surfaces_the_honored_filter_and_subscription_id():
    """Entering waits for the ack: `honored` and `subscription_id` are populated
    before the first event is consumed."""
    bus = InMemorySubscriptionBus()
    async with Client(_bus_server(bus)) as client:
        with anyio.fail_after(5):
            async with client.listen(  # pragma: no branch
                tools_list_changed=True, resource_subscriptions=["note://todo"]
            ) as sub:
                assert isinstance(sub, Subscription)
                assert sub.honored.tools_list_changed is True
                assert sub.honored.resource_subscriptions == ["note://todo"]
                assert isinstance(sub.subscription_id, str)
                assert sub.subscription_id.startswith("listen-")


async def test_listen_delivers_all_four_typed_event_kinds():
    """Bus publishes come back as the same typed event values, in order."""
    bus = InMemorySubscriptionBus()
    async with Client(_bus_server(bus)) as client:
        with anyio.fail_after(5):
            async with client.listen(  # pragma: no branch
                tools_list_changed=True,
                prompts_list_changed=True,
                resources_list_changed=True,
                resource_subscriptions=["note://todo"],
            ) as sub:
                for event in (
                    ToolsListChanged(),
                    PromptsListChanged(),
                    ResourcesListChanged(),
                    ResourceUpdated(uri="note://todo"),
                ):
                    await bus.publish(event)
                    assert await anext(sub) == event


async def test_unconsumed_duplicate_events_coalesce():
    """Events are level triggers: duplicates pending consumption collapse to one,
    so a slow consumer wakes once per distinct fact, not once per publish."""
    bus = InMemorySubscriptionBus()
    async with Client(_bus_server(bus)) as client:
        with anyio.fail_after(5):
            async with client.listen(  # pragma: no branch
                tools_list_changed=True, resource_subscriptions=["note://todo"]
            ) as sub:
                for _ in range(3):
                    await bus.publish(ToolsListChanged())
                await bus.publish(ResourceUpdated(uri="note://todo"))
                await anyio.wait_all_tasks_blocked()
                assert await anext(sub) == ToolsListChanged()
                # The duplicates collapsed: the next event is the resource update.
                assert await anext(sub) == ResourceUpdated(uri="note://todo")


async def test_graceful_server_close_ends_the_loop_cleanly():
    """The server's deliberate close (the empty listen result) ends iteration
    without an exception - a clean end, not a loss."""
    bus = InMemorySubscriptionBus()
    handler = ListenHandler(bus)
    server = Server("subs", on_subscriptions_listen=handler)
    events: list[object] = []
    async with Client(server) as client:
        with anyio.fail_after(5):
            async with client.listen(tools_list_changed=True) as sub:  # pragma: no branch
                await bus.publish(ToolsListChanged())
                handler.close()
                events.extend([event async for event in sub])
    # The event published before the close was still delivered.
    assert events == [ToolsListChanged()]


async def test_abrupt_stream_end_raises_subscription_lost():
    """A stream that dies without the graceful result raises `SubscriptionLost`
    from iteration, with the underlying error chained."""
    proceed = anyio.Event()

    async def dropping_listen(
        ctx: ServerRequestContext[Any, Any], params: types.SubscriptionsListenRequestParams
    ) -> types.SubscriptionsListenResult:
        await _ack(ctx, params.notifications)
        await proceed.wait()
        raise MCPError(types.INTERNAL_ERROR, "stream torn down")

    server = Server("subs", on_subscriptions_listen=dropping_listen)
    async with Client(server) as client:
        with anyio.fail_after(5):
            async with client.listen(tools_list_changed=True) as sub:  # pragma: no branch
                proceed.set()
                with pytest.raises(SubscriptionLost) as exc_info:  # pragma: no branch
                    await anext(sub)
    assert isinstance(exc_info.value.__cause__, MCPError)
    assert exc_info.value.__cause__.error.message == "stream torn down"


async def test_listen_on_a_legacy_connection_raises_the_typed_steer():
    """On a 2025 connection `listen` fails fast with the typed error steering to
    the legacy verbs, instead of leaking a -32601 from the wire."""
    bus = InMemorySubscriptionBus()
    async with Client(_bus_server(bus), mode="legacy") as client:
        with anyio.fail_after(5):
            # Entering is where the guard fires; __aenter__ directly avoids an unreachable with-body.
            with pytest.raises(ListenNotSupportedError) as exc_info:  # pragma: no branch
                await client.listen(tools_list_changed=True).__aenter__()
    assert exc_info.value.negotiated_version == "2025-11-25"
    assert "subscribe_resource" in str(exc_info.value)


async def test_server_rejection_raises_from_enter_not_from_iteration():
    """A server without the listen handler rejects the request; the error surfaces
    immediately from entering the context (raise, don't degrade)."""
    server = Server("no-listen")
    async with Client(server) as client:
        with anyio.fail_after(5):
            with pytest.raises(MCPError) as exc_info:  # pragma: no branch
                await client.listen(tools_list_changed=True).__aenter__()
    assert exc_info.value.error.code == types.METHOD_NOT_FOUND


async def test_immediate_result_without_ack_opens_already_closed():
    """A server answering with the bare result and no ack yields a subscription
    that is already gracefully over: empty honored filter, no events."""

    async def degenerate_listen(
        ctx: ServerRequestContext[Any, Any], params: types.SubscriptionsListenRequestParams
    ) -> types.SubscriptionsListenResult:
        assert ctx.request_id is not None
        return types.SubscriptionsListenResult(_meta={SUBSCRIPTION_ID_META_KEY: ctx.request_id})

    server = Server("subs", on_subscriptions_listen=degenerate_listen)
    async with Client(server) as client:
        with anyio.fail_after(5):
            async with client.listen(tools_list_changed=True) as sub:  # pragma: no branch
                assert sub.honored == SubscriptionFilter()
                with pytest.raises(StopAsyncIteration):  # pragma: no branch
                    await anext(sub)


async def test_server_sent_cancelled_for_the_listen_id_raises_subscription_lost():
    """A server tearing the stream down with notifications/cancelled (the
    stream-transport spelling) surfaces as a lost subscription."""
    proceed = anyio.Event()

    async def cancelling_listen(
        ctx: ServerRequestContext[Any, Any], params: types.SubscriptionsListenRequestParams
    ) -> types.SubscriptionsListenResult:
        assert ctx.request_id is not None
        await _ack(ctx, params.notifications)
        await proceed.wait()
        await ctx.session.send_notification(
            types.CancelledNotification(params=types.CancelledNotificationParams(request_id=ctx.request_id)),
            related_request_id=ctx.request_id,
        )
        await anyio.sleep_forever()
        raise AssertionError("unreachable")  # pragma: no cover

    server = Server("subs", on_subscriptions_listen=cancelling_listen)
    async with Client(server) as client:
        with anyio.fail_after(5):
            async with client.listen(tools_list_changed=True) as sub:  # pragma: no branch
                proceed.set()
                with pytest.raises(SubscriptionLost):  # pragma: no branch
                    await anext(sub)


async def test_exiting_the_context_frees_the_server_slot():
    """Leaving the block ends the subscription server-side: with a one-slot
    handler, a second listen succeeds only because the first was released."""
    bus = InMemorySubscriptionBus()
    async with Client(_bus_server(bus, max_subscriptions=1)) as client:
        with anyio.fail_after(5):
            async with client.listen(tools_list_changed=True) as first:
                assert first.honored.tools_list_changed is True
            async with client.listen(tools_list_changed=True) as second:  # pragma: no branch
                assert second.honored.tools_list_changed is True
                assert second.subscription_id != first.subscription_id


async def test_concurrent_subscriptions_demux_independently():
    """Two open subscriptions each receive only their own filter's events."""
    bus = InMemorySubscriptionBus()
    async with Client(_bus_server(bus)) as client:
        with anyio.fail_after(5):
            async with (  # pragma: no branch
                client.listen(tools_list_changed=True) as tools_sub,
                client.listen(resource_subscriptions=["note://todo"]) as notes_sub,
            ):
                await bus.publish(ToolsListChanged())
                await bus.publish(ResourceUpdated(uri="note://todo"))
                assert await anext(tools_sub) == ToolsListChanged()
                assert await anext(notes_sub) == ResourceUpdated(uri="note://todo")
                # Neither stream received the other's event.
                await bus.publish(ToolsListChanged())
                assert await anext(tools_sub) == ToolsListChanged()


async def test_change_notifications_still_reach_message_handler():
    """The demux tees: a delivered event's notification still flows to
    message_handler (cache eviction and observers keep working); the ack is
    driver state and is consumed."""
    bus = InMemorySubscriptionBus()
    seen: list[str] = []

    async def on_message(message: object) -> None:
        # The ack never reaches the handler - it is driver state, consumed by the demux.
        assert not isinstance(message, types.SubscriptionsAcknowledgedNotification)
        if isinstance(message, types.ToolListChangedNotification):  # pragma: no branch
            seen.append("tools-changed")

    async with Client(_bus_server(bus), message_handler=on_message) as client:
        with anyio.fail_after(5):
            async with client.listen(tools_list_changed=True) as sub:  # pragma: no branch
                await bus.publish(ToolsListChanged())
                assert await anext(sub) == ToolsListChanged()
                await anyio.wait_all_tasks_blocked()
    assert seen == ["tools-changed"]


async def test_enter_times_out_when_the_ack_never_arrives():
    """The ack wait rides the session's read timeout, so a wedged server cannot
    hang the open forever."""

    async def silent_listen(
        ctx: ServerRequestContext[Any, Any], params: types.SubscriptionsListenRequestParams
    ) -> types.SubscriptionsListenResult:
        await anyio.sleep_forever()
        raise AssertionError("unreachable")  # pragma: no cover

    server = Server("subs", on_subscriptions_listen=silent_listen)
    async with Client(server, read_timeout_seconds=0.05) as client:
        with anyio.fail_after(5):
            with pytest.raises(TimeoutError):  # pragma: no branch
                await client.listen(tools_list_changed=True).__aenter__()


async def test_an_open_stream_outlives_the_session_read_timeout():
    """The listen request itself is exempt from the read timeout: the stream
    stays open and delivers long after the per-request deadline passed."""
    bus = InMemorySubscriptionBus()
    async with Client(_bus_server(bus), read_timeout_seconds=0.05) as client:
        with anyio.fail_after(5):
            async with client.listen(tools_list_changed=True) as sub:  # pragma: no branch
                # Real clock on purpose: this pins a timeout feature.
                await anyio.sleep(0.2)
                await bus.publish(ToolsListChanged())
                assert await anext(sub) == ToolsListChanged()


async def test_a_duplicate_ack_does_not_overwrite_the_honored_filter():
    """The first ack wins; a later conflicting ack is a no-op."""
    proceed = anyio.Event()

    async def double_acking_listen(
        ctx: ServerRequestContext[Any, Any], params: types.SubscriptionsListenRequestParams
    ) -> types.SubscriptionsListenResult:
        assert ctx.request_id is not None
        await _ack(ctx, params.notifications)
        await _ack(ctx, SubscriptionFilter())
        await proceed.wait()
        return types.SubscriptionsListenResult(_meta={SUBSCRIPTION_ID_META_KEY: ctx.request_id})

    server = Server("subs", on_subscriptions_listen=double_acking_listen)
    async with Client(server) as client:
        with anyio.fail_after(5):
            async with client.listen(tools_list_changed=True) as sub:  # pragma: no branch
                assert sub.honored.tools_list_changed is True
                proceed.set()


async def test_a_non_event_frame_with_the_subscription_id_is_teed_not_delivered():
    """A stamped notification that is not a change event (a log line on the
    stream) never surfaces as an event; it flows to message_handler as usual."""
    proceed = anyio.Event()

    async def logging_listen(
        ctx: ServerRequestContext[Any, Any], params: types.SubscriptionsListenRequestParams
    ) -> types.SubscriptionsListenResult:
        assert ctx.request_id is not None
        meta = await _ack(ctx, params.notifications)
        await ctx.session.send_notification(
            types.LoggingMessageNotification(
                params=types.LoggingMessageNotificationParams(level="info", data="not an event", _meta=meta)
            ),
            related_request_id=ctx.request_id,
        )
        await proceed.wait()
        return types.SubscriptionsListenResult(_meta=meta)

    logged: list[str] = []

    async def on_message(message: object) -> None:
        if isinstance(message, types.LoggingMessageNotification):  # pragma: no branch
            logged.append(str(message.params.data))

    server = Server("subs", on_subscriptions_listen=logging_listen)
    async with Client(server, message_handler=on_message) as client:
        with anyio.fail_after(5):
            async with client.listen(tools_list_changed=True) as sub:  # pragma: no branch
                await anyio.wait_all_tasks_blocked()
                proceed.set()
                with pytest.raises(StopAsyncIteration):  # pragma: no branch
                    await anext(sub)
    assert logged == ["not an event"]


async def test_session_teardown_unblocks_a_sibling_consumer_with_subscription_lost():
    """Closing the client while a watcher task is parked on the stream must not
    strand it: teardown settles every open route as lost."""
    bus = InMemorySubscriptionBus()
    outcome: list[str] = []
    entered = anyio.Event()

    async def consume(client: Client) -> None:
        with pytest.raises(SubscriptionLost):
            async with client.listen(tools_list_changed=True) as sub:
                entered.set()
                await anext(sub)
        outcome.append("lost")

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            async with Client(_bus_server(bus)) as client:  # pragma: no branch
                tg.start_soon(consume, client)
                await entered.wait()
            # The client exited above while the watcher was still parked on the
            # stream; teardown settles the route, unblocking it with a lost end.
    assert outcome == ["lost"]


async def test_server_cancel_before_the_ack_raises_subscription_lost_from_enter():
    """A stream torn down before it was ever acknowledged is a failed open:
    enter raises instead of yielding a handle with a fabricated empty filter."""

    async def cancel_first_listen(
        ctx: ServerRequestContext[Any, Any], params: types.SubscriptionsListenRequestParams
    ) -> types.SubscriptionsListenResult:
        assert ctx.request_id is not None
        await ctx.session.send_notification(
            types.CancelledNotification(params=types.CancelledNotificationParams(request_id=ctx.request_id)),
            related_request_id=ctx.request_id,
        )
        await anyio.sleep_forever()
        raise AssertionError("unreachable")  # pragma: no cover

    server = Server("subs", on_subscriptions_listen=cancel_first_listen)
    async with Client(server) as client:
        with anyio.fail_after(5):
            with pytest.raises(SubscriptionLost, match="before it was acknowledged"):  # pragma: no branch
                await client.listen(tools_list_changed=True).__aenter__()


async def test_listen_on_an_exited_session_raises_and_leaks_no_route():
    """Opening against a session whose context already exited fails loudly, and
    the demux registration does not outlive the failed open."""
    bus = InMemorySubscriptionBus()
    client = Client(_bus_server(bus))
    async with client:
        session = client.session
    with pytest.raises(RuntimeError):
        await listen(session, tools_list_changed=True).__aenter__()
    assert session._listen_routes == {}  # pyright: ignore[reportPrivateUsage]


async def test_listen_on_a_never_entered_session_raises_runtime_error():
    """An adopted-but-never-entered session has no task group to drive the stream."""
    dispatcher, _peer = create_direct_dispatcher_pair()
    session = ClientSession(dispatcher=dispatcher)
    session.adopt(
        types.DiscoverResult(
            supported_versions=["2026-07-28"],
            capabilities=types.ServerCapabilities(),
            server_info=types.Implementation(name="stub", version="0"),
        )
    )
    with pytest.raises(RuntimeError, match="entered session"):
        await listen(session, tools_list_changed=True).__aenter__()
    assert session._listen_routes == {}  # pyright: ignore[reportPrivateUsage]


async def test_a_retained_handle_after_exit_does_not_serve_stale_events():
    """Leaving the block abandons the backlog: a stashed handle must not replay
    buffered events as if they were live."""
    bus = InMemorySubscriptionBus()
    async with Client(_bus_server(bus)) as client:
        with anyio.fail_after(5):
            async with client.listen(tools_list_changed=True) as sub:
                await bus.publish(ToolsListChanged())
                await anyio.wait_all_tasks_blocked()
            with pytest.raises(StopAsyncIteration):  # pragma: no branch
                await anext(sub)


async def test_a_stray_ack_outside_the_driver_namespace_still_reaches_message_handler():
    """Acks for ids the driver never minted flow to message_handler - the raw
    escape-hatch listen (send_request directly) observes its ack there."""
    proceed = anyio.Event()

    async def stray_acking_listen(
        ctx: ServerRequestContext[Any, Any], params: types.SubscriptionsListenRequestParams
    ) -> types.SubscriptionsListenResult:
        assert ctx.request_id is not None
        await _ack(ctx, params.notifications)
        await ctx.session.send_notification(
            types.SubscriptionsAcknowledgedNotification(
                params=types.SubscriptionsAcknowledgedNotificationParams(
                    notifications=SubscriptionFilter(), _meta={SUBSCRIPTION_ID_META_KEY: 424242}
                )
            ),
            related_request_id=ctx.request_id,
        )
        await proceed.wait()
        return types.SubscriptionsListenResult(_meta={SUBSCRIPTION_ID_META_KEY: ctx.request_id})

    handled: list[str] = []

    async def on_message(message: object) -> None:
        handled.append(type(message).__name__)

    server = Server("subs", on_subscriptions_listen=stray_acking_listen)
    async with Client(server, message_handler=on_message) as client:
        with anyio.fail_after(5):
            async with client.listen(tools_list_changed=True) as sub:  # pragma: no branch
                await anyio.wait_all_tasks_blocked()
                proceed.set()
                with pytest.raises(StopAsyncIteration):  # pragma: no branch
                    await anext(sub)
    assert "SubscriptionsAcknowledgedNotification" in handled


async def test_a_bare_string_for_resource_subscriptions_is_rejected():
    """`resource_subscriptions="uri"` would explode into per-character URIs; the
    classic footgun is rejected before anything touches the wire."""
    bus = InMemorySubscriptionBus()
    async with Client(_bus_server(bus)) as client:
        with pytest.raises(TypeError, match="sequence of URIs"):
            await client.listen(resource_subscriptions="note://todo").__aenter__()  # pyright: ignore[reportArgumentType]


async def test_a_raw_request_id_collision_fails_the_subscription_not_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raw caller occupying the driver's next minted id fails that ONE listen
    with a typed error from enter; the session survives and the next listen
    (a fresh id) opens normally."""
    monkeypatch.setattr(subscriptions_module, "_listen_ids", count(7000))
    bus = InMemorySubscriptionBus()
    async with Client(_bus_server(bus)) as client:
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch
                raw_scope = anyio.CancelScope()

                async def raw_listen() -> None:
                    request = types.SubscriptionsListenRequest(
                        params=types.SubscriptionsListenRequestParams(
                            notifications=SubscriptionFilter(tools_list_changed=True)
                        )
                    )
                    data = request.model_dump(by_alias=True, mode="json", exclude_none=True)
                    opts: CallOptions = {"request_id": "listen-7000"}
                    client.session._stamp(data, opts)  # pyright: ignore[reportPrivateUsage]
                    with raw_scope:
                        await client.session._dispatcher.send_raw_request(  # pyright: ignore[reportPrivateUsage]
                            data["method"], data.get("params"), opts
                        )

                tg.start_soon(raw_listen)
                await anyio.wait_all_tasks_blocked()
                with pytest.raises(MCPError) as exc_info:
                    await client.listen(tools_list_changed=True).__aenter__()
                assert "already in flight" in exc_info.value.error.message
                raw_scope.cancel()
                # The session is intact: the next listen mints a fresh id and opens.
                async with client.listen(tools_list_changed=True) as sub:  # pragma: no branch
                    assert sub.subscription_id == "listen-7001"
