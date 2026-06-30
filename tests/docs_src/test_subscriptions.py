"""`docs/advanced/subscriptions.md`: every claim the page makes, proved against the real SDK."""

from typing import Any

import anyio
import mcp_types as types
import pytest

from docs_src.subscriptions import tutorial001, tutorial002
from mcp import Client
from mcp.server.subscriptions import SUBSCRIPTION_ID_META_KEY, ToolsListChanged

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


class _Stream:
    """Collects listen-stream notifications and lets tests await arrival counts."""

    def __init__(self) -> None:
        self.received: list[types.ServerNotification] = []
        self._arrival = anyio.Event()

    async def handler(
        self,
        message: object,
    ) -> None:
        # The only messages these connections produce are the stream's frames.
        assert isinstance(
            message,
            types.SubscriptionsAcknowledgedNotification
            | types.ResourceUpdatedNotification
            | types.ToolListChangedNotification,
        ), message
        self.received.append(message)
        self._arrival.set()
        self._arrival = anyio.Event()

    async def wait_for(self, count: int) -> None:
        with anyio.fail_after(5):
            while len(self.received) < count:
                await self._arrival.wait()


def _listen_request(**fields: Any) -> types.SubscriptionsListenRequest:
    return types.SubscriptionsListenRequest(
        params=types.SubscriptionsListenRequestParams(notifications=types.SubscriptionFilter(**fields))
    )


async def test_publishes_reach_the_stream_filtered_and_tagged() -> None:
    """tutorial001: the full arc - ack first, exact-URI filtering, list_changed
    leading to a refreshed tool list, and client-side close."""
    stream = _Stream()
    async with Client(tutorial001.mcp, mode="2026-07-28", message_handler=stream.handler) as client:
        async with anyio.create_task_group() as tg:

            async def listen() -> None:
                await client.session.send_request(
                    _listen_request(tools_list_changed=True, resource_subscriptions=["note://todo"]),
                    types.SubscriptionsListenResult,
                )

            tg.start_soon(listen)
            await stream.wait_for(1)

            ack = stream.received[0]
            assert isinstance(ack, types.SubscriptionsAcknowledgedNotification)
            assert ack.params.notifications == types.SubscriptionFilter(
                tools_list_changed=True, resource_subscriptions=["note://todo"]
            )
            assert ack.params.meta is not None and SUBSCRIPTION_ID_META_KEY in ack.params.meta

            # An edit to a URI the stream did not subscribe to stays silent...
            await client.call_tool("edit_note", {"name": "journal", "text": "day two"})
            # ...and the subscribed URI delivers, tagged with the same subscription id.
            await client.call_tool("edit_note", {"name": "todo", "text": "water plants"})
            await stream.wait_for(2)
            updated = stream.received[1]
            assert isinstance(updated, types.ResourceUpdatedNotification)
            assert updated.params.uri == "note://todo"
            assert updated.params.meta == ack.params.meta

            await client.call_tool("enable_search", {})
            await stream.wait_for(3)
            assert isinstance(stream.received[2], types.ToolListChangedNotification)

            # The client ends the stream by closing it - cancel the parked request.
            tg.cancel_scope.cancel()

        # The list_changed told us to re-fetch: the new tool is there, and the
        # session outlives the closed stream.
        tools = await client.list_tools()
        assert "search" in {tool.name for tool in tools.tools}
        contents = (await client.read_resource("note://todo")).contents[0]
        assert isinstance(contents, types.TextResourceContents)
        assert contents.text == "water plants"


async def test_publish_with_no_subscribers_is_a_no_op() -> None:
    """tutorial001: publishing to an idle server does nothing and breaks nothing."""
    async with Client(tutorial001.mcp, mode="2026-07-28") as client:
        result = await client.call_tool("edit_note", {"name": "todo", "text": "buy milk"})
        assert result.is_error is not True


async def test_lowlevel_composition_serves_the_same_stream() -> None:
    """tutorial002: bus + ListenHandler on the lowlevel Server is the same machinery."""
    stream = _Stream()
    async with Client(tutorial002.server, mode="2026-07-28", message_handler=stream.handler) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools.tools] == ["edit_note"]

        async with anyio.create_task_group() as tg:

            async def listen() -> None:
                await client.session.send_request(
                    _listen_request(resource_subscriptions=["note://todo"]),
                    types.SubscriptionsListenResult,
                )

            tg.start_soon(listen)
            await stream.wait_for(1)

            await client.call_tool("edit_note", {"name": "todo", "text": "water plants"})
            await stream.wait_for(2)
            updated = stream.received[1]
            assert isinstance(updated, types.ResourceUpdatedNotification)
            assert updated.params.uri == "note://todo"

            # The bus you constructed is also the publish surface outside a
            # request; an unrequested kind never reaches this stream.
            await tutorial002.bus.publish(ToolsListChanged())
            await client.call_tool("edit_note", {"name": "todo", "text": "done"})
            await stream.wait_for(3)
            assert isinstance(stream.received[2], types.ResourceUpdatedNotification)

            tg.cancel_scope.cancel()
