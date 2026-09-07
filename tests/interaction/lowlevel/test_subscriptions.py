"""Client.listen stream endings, stamping, filtering and limits against lowlevel servers over the connect matrix."""

from typing import Any

import anyio
import mcp_types as types
import pytest
from mcp_types import INTERNAL_ERROR, ErrorData

from mcp import MCPError
from mcp.client import IncomingMessage
from mcp.client.subscriptions import PromptsListChanged, SubscriptionLost, ToolsListChanged
from mcp.server import Server, ServerRequestContext
from mcp.server.subscriptions import SUBSCRIPTION_ID_META_KEY, InMemorySubscriptionBus, ListenHandler
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _stamps(teed: list[IncomingMessage]) -> list[tuple[str, object]]:
    """(method, subscriptionId stamp) per teed frame, checked here because the session swallows a raising handler."""
    stamps: list[tuple[str, object]] = []
    for message in teed:
        assert isinstance(message, types.ServerNotification)
        assert message.params is not None
        stamps.append((message.method, (message.params.meta or {}).get(SUBSCRIPTION_ID_META_KEY)))
    return stamps


@requirement("subscriptions:listen:graceful-close")
async def test_a_graceful_server_close_ends_iteration_after_buffered_events(connect: Connect) -> None:
    """`ListenHandler.close()` sends the result last; iteration drains published events, then ends cleanly."""
    bus = InMemorySubscriptionBus()
    handler = ListenHandler(bus)
    server = Server("subs", on_subscriptions_listen=handler)
    events: list[object] = []
    async with connect(server) as client:
        with anyio.fail_after(10):
            async with client.listen(tools_list_changed=True) as sub:  # pragma: no branch
                await bus.publish(ToolsListChanged())
                handler.close()
                events.extend([event async for event in sub])
    assert events == [ToolsListChanged()]


@requirement("subscriptions:listen:client:lost")
async def test_a_stream_dropped_after_the_ack_raises_subscription_lost(connect: Connect) -> None:
    """Erroring the listen request after the ack (abrupt, not graceful) raises SubscriptionLost from iteration."""
    proceed = anyio.Event()

    async def dropping_listen(
        ctx: ServerRequestContext[Any, Any], params: types.SubscriptionsListenRequestParams
    ) -> types.SubscriptionsListenResult:
        assert ctx.request_id is not None
        await ctx.session.send_notification(
            types.SubscriptionsAcknowledgedNotification(
                params=types.SubscriptionsAcknowledgedNotificationParams(
                    notifications=params.notifications,
                    _meta={SUBSCRIPTION_ID_META_KEY: ctx.request_id},
                )
            ),
            related_request_id=ctx.request_id,
        )
        await proceed.wait()
        raise MCPError(types.INTERNAL_ERROR, "stream torn down")

    server = Server("subs", on_subscriptions_listen=dropping_listen)
    async with connect(server) as client:
        with anyio.fail_after(10):
            async with client.listen(tools_list_changed=True) as sub:  # pragma: no branch
                proceed.set()
                with pytest.raises(SubscriptionLost):  # pragma: no branch
                    await anext(sub)


@requirement("subscriptions:listen:ack-first-stamped")
@requirement("protocol:request-id:caller-supplied")
async def test_the_subscription_id_is_the_listen_request_id_the_server_saw(connect: Connect) -> None:
    """The handle's `subscription_id` is the listen request's own JSON-RPC id, known to the caller
    while the request is still in flight - the key the server stamps every frame with for demux.

    The assertion runs inside the open stream: the ack has arrived but the listen request's
    response has not, so the id cannot have come from a response.
    """
    bus = InMemorySubscriptionBus()
    stock = ListenHandler(bus)
    seen: list[types.RequestId] = []

    async def recording_listen(
        ctx: ServerRequestContext[Any, Any], params: types.SubscriptionsListenRequestParams
    ) -> types.SubscriptionsListenResult:
        assert ctx.request_id is not None
        seen.append(ctx.request_id)
        return await stock(ctx, params)

    server = Server("subs", on_subscriptions_listen=recording_listen)
    async with connect(server) as client:
        with anyio.fail_after(10):
            async with client.listen(tools_list_changed=True) as sub:  # pragma: no branch
                assert seen == [sub.subscription_id]
                stock.close()
                async for _event in sub:
                    raise NotImplementedError  # unreachable: nothing was published


@requirement("subscriptions:listen:client:concurrent-demux")
@requirement("protocol:request-id:caller-supplied")
async def test_concurrent_listen_streams_each_receive_their_own_ack(connect: Connect) -> None:
    """Two subscriptions opened concurrently each surface the honored filter of their own request:
    ack frames route by subscription id, not broadcast to every open route.

    The server gates both acks until both listen requests have arrived, so both client routes are
    live and unacknowledged when the first ack lands - a client that broadcast subscription frames
    would cross-pollute that ack into both handles.
    """
    bus = InMemorySubscriptionBus()
    stock = ListenHandler(bus)
    arrived: list[types.RequestId] = []
    both_arrived = anyio.Event()

    async def gated_listen(
        ctx: ServerRequestContext[Any, Any], params: types.SubscriptionsListenRequestParams
    ) -> types.SubscriptionsListenResult:
        assert ctx.request_id is not None
        arrived.append(ctx.request_id)
        if len(arrived) == 2:
            both_arrived.set()
        with anyio.fail_after(10):
            await both_arrived.wait()
        return await stock(ctx, params)

    server = Server("subs", on_subscriptions_listen=gated_listen)
    honored: dict[str, types.SubscriptionFilter] = {}

    async with connect(server) as client:

        async def open_tools() -> None:
            async with client.listen(tools_list_changed=True) as sub:
                honored["tools"] = sub.honored

        async def open_prompts() -> None:
            async with client.listen(prompts_list_changed=True) as sub:
                honored["prompts"] = sub.honored

        with anyio.fail_after(10):
            async with anyio.create_task_group() as tg:  # pragma: no branch
                tg.start_soon(open_tools)
                tg.start_soon(open_prompts)

    assert honored == {
        "tools": types.SubscriptionFilter(tools_list_changed=True),
        "prompts": types.SubscriptionFilter(prompts_list_changed=True),
    }
    assert len(set(arrived)) == 2


@requirement("subscriptions:listen:notification-stamped")
async def test_every_event_frame_on_a_listen_stream_is_stamped_with_the_listen_request_id(connect: Connect) -> None:
    """Each event notification the server delivers carries the stream's own listen request id under
    the subscriptionId `_meta` key; the frames still tee to `message_handler`, where the stamp is read.

    The stamp is spec-mandated; the tee is SDK-defined. The teed list is complete once iteration ends:
    the listen result that closes the stream arrives after both event frames, and the recorder is a
    plain append.
    """
    bus = InMemorySubscriptionBus()
    handler = ListenHandler(bus)
    server = Server("subs", on_subscriptions_listen=handler)
    teed: list[IncomingMessage] = []

    async def record(message: IncomingMessage) -> None:
        teed.append(message)

    async with connect(server, message_handler=record) as client:
        with anyio.fail_after(5):
            async with client.listen(tools_list_changed=True, prompts_list_changed=True) as sub:
                await bus.publish(ToolsListChanged())
                await bus.publish(PromptsListChanged())
                handler.close()
                events = [event async for event in sub]
            assert events == [ToolsListChanged(), PromptsListChanged()]

    assert _stamps(teed) == [
        ("notifications/tools/list_changed", sub.subscription_id),
        ("notifications/prompts/list_changed", sub.subscription_id),
    ]


@requirement("subscriptions:listen:per-stream-filter")
@requirement("subscriptions:listen:concurrent-demux")
async def test_concurrent_streams_each_yield_only_the_kinds_their_own_filter_requested(connect: Connect) -> None:
    """Two concurrent listen streams with disjoint filters each yield only their own kind, and every
    delivered frame is stamped with the id of the stream it belongs to.

    Filter and stamp are spec-mandated; how they hold is per transport. In memory both streams share
    one channel, so the client's demux by stamp keeps them apart; over streamable HTTP each stream is
    its own response, so the server's per-stream admission is what keeps the foreign kind out.
    """
    bus = InMemorySubscriptionBus()
    handler = ListenHandler(bus)
    server = Server("subs", on_subscriptions_listen=handler)
    teed: list[IncomingMessage] = []

    async def record(message: IncomingMessage) -> None:
        teed.append(message)

    async with connect(server, message_handler=record) as client:
        with anyio.fail_after(5):
            async with (
                client.listen(tools_list_changed=True) as tools_sub,
                client.listen(prompts_list_changed=True) as prompts_sub,
            ):
                await bus.publish(PromptsListChanged())
                await bus.publish(ToolsListChanged())
                handler.close()
                tools_events = [event async for event in tools_sub]
                prompts_events = [event async for event in prompts_sub]
            assert tools_events == [ToolsListChanged()]
            assert prompts_events == [PromptsListChanged()]

    stamped = _stamps(teed)
    assert len(stamped) == 2
    assert set(stamped) == {
        ("notifications/prompts/list_changed", prompts_sub.subscription_id),
        ("notifications/tools/list_changed", tools_sub.subscription_id),
    }


@requirement("subscriptions:listen:capacity-guard")
async def test_a_listen_beyond_the_subscription_limit_is_refused_in_band_and_leaves_the_open_stream_intact(
    connect: Connect,
) -> None:
    """`ListenHandler(max_subscriptions=1)` refuses a second concurrent listen with an in-band error
    before any acknowledgment, so entering raises; the first stream keeps delivering and closes cleanly.

    SDK-defined: the limit and its error are the lowlevel handler's own.
    """
    bus = InMemorySubscriptionBus()
    handler = ListenHandler(bus, max_subscriptions=1)
    server = Server("subs", on_subscriptions_listen=handler)

    async with connect(server) as client:
        with anyio.fail_after(5):
            async with client.listen(tools_list_changed=True) as first:
                with pytest.raises(MCPError) as refused:
                    async with client.listen(prompts_list_changed=True):
                        raise NotImplementedError  # unreachable: refused before the acknowledgment
                await bus.publish(ToolsListChanged())
                handler.close()
                events = [event async for event in first]
            assert events == [ToolsListChanged()]

    assert refused.value.error == ErrorData(code=INTERNAL_ERROR, message="Subscription limit reached")
