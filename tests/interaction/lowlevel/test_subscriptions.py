"""Client.listen stream endings against lowlevel servers over the connect matrix."""

from typing import Any

import anyio
import mcp_types as types
import pytest

from mcp import MCPError
from mcp.client.subscriptions import SubscriptionLost, ToolsListChanged
from mcp.server import Server, ServerRequestContext
from mcp.server.subscriptions import SUBSCRIPTION_ID_META_KEY, InMemorySubscriptionBus, ListenHandler
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("subscriptions:listen:client:graceful-close")
async def test_a_graceful_server_close_ends_iteration_after_buffered_events(connect: Connect) -> None:
    """`ListenHandler.close()` sends the stamped result as the final frame; the
    client loop drains what was published first, then ends without an exception."""
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
    """A server erroring the listen request after the ack (an abrupt end, not the
    graceful close) surfaces as SubscriptionLost at the iteration site."""
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
