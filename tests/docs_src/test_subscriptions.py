"""`docs/handlers/subscriptions.md`: every claim the page makes, proved against the real SDK."""

from typing import Any

import anyio
import mcp_types as types
import pytest
from trio.testing import MockClock

from docs_src.subscriptions import tutorial001, tutorial002, tutorial003, tutorial004
from mcp import Client
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.subscriptions import (
    SUBSCRIPTION_ID_META_KEY,
    InMemorySubscriptionBus,
    ListenHandler,
    ResourceUpdated,
    ToolsListChanged,
)

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


async def test_client_listen_delivers_one_typed_event_then_closes() -> None:
    """tutorial003: `Client.listen` yields typed events for the subscribed URI; leaving the block closes the stream."""
    results: list[str] = []

    async def watch() -> None:
        results.append(await tutorial003.watch_todo())

    with anyio.fail_after(10):
        async with anyio.create_task_group() as tg:
            tg.start_soon(watch)
            # Let the watcher park on its stream (ack complete) before the edit is published.
            await anyio.wait_all_tasks_blocked()
            async with Client(tutorial001.mcp) as editor:  # pragma: no branch
                await editor.call_tool("edit_note", {"name": "todo", "text": "water plants"})
    assert results == ["changed: note://todo"]


class _Reads:
    """Counts server-side resource reads and lets tests await a count."""

    def __init__(self) -> None:
        self.count = 0
        self._bump = anyio.Event()

    def hit(self) -> None:
        self.count += 1
        self._bump.set()
        self._bump = anyio.Event()

    async def wait_for(self, count: int) -> None:
        with anyio.fail_after(5):
            while self.count < count:
                await self._bump.wait()


@pytest.mark.parametrize(
    "anyio_backend",
    [pytest.param(("trio", {"clock": MockClock(autojump_threshold=0)}), id="trio-mockclock")],
)
async def test_watcher_re_listens_after_both_endings() -> None:
    """tutorial004: watch() refetches on entry and per event, and re-listens after
    a graceful server close and after `SubscriptionLost`.

    Runs on trio's autojumping MockClock so the loop's backoff sleep takes no wall-clock time."""
    DROP_SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {"subscription_id": {"type": "string"}},
        "required": ["subscription_id"],
    }
    bus = InMemorySubscriptionBus()
    handler = ListenHandler(bus)
    reads = _Reads()
    stream = _Stream()

    async def read_resource(
        ctx: ServerRequestContext[Any], params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        reads.hit()
        return types.ReadResourceResult(contents=[types.TextResourceContents(uri=params.uri, text="fresh")])

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="drop", description="End a subscription abruptly.", input_schema=DROP_SCHEMA)]
        )

    async def drop_stream(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        # The abrupt ending: the server cancels the named subscription without a
        # graceful close. Sent request-scoped: the 2026 wire has no standalone stream.
        subscription_id = (params.arguments or {})["subscription_id"]
        await ctx.session.send_notification(
            types.CancelledNotification(params=types.CancelledNotificationParams(request_id=subscription_id)),
            related_request_id=ctx.request_id,
        )
        return types.CallToolResult(content=[])

    server = Server(
        "watched",
        on_read_resource=read_resource,
        on_list_tools=list_tools,
        on_call_tool=drop_stream,
        on_subscriptions_listen=handler,
    )

    def teed_subscription_id(index: int) -> Any:
        updated = stream.received[index]
        assert isinstance(updated, types.ResourceUpdatedNotification)
        assert updated.params.meta is not None
        return updated.params.meta[SUBSCRIPTION_ID_META_KEY]

    async with Client(server, mode="2026-07-28", message_handler=stream.handler) as client:
        async with anyio.create_task_group() as tg:
            tg.start_soon(tutorial004.watch, client, "note://todo")

            # Stream 1: the entry refetch proves the ack arrived; an event drives one more refetch.
            await reads.wait_for(1)
            await bus.publish(ResourceUpdated(uri="note://todo"))
            await reads.wait_for(2)
            await stream.wait_for(1)

            # Graceful close: the watcher backs off, re-listens, and refetches.
            handler.close()
            await reads.wait_for(3)
            await bus.publish(ResourceUpdated(uri="note://todo"))
            await reads.wait_for(4)
            await stream.wait_for(2)
            second_id = teed_subscription_id(1)
            assert second_id != teed_subscription_id(0)

            # Abrupt ending: the watcher swallows SubscriptionLost and re-listens again.
            await client.call_tool("drop", {"subscription_id": second_id})
            await reads.wait_for(5)
            await bus.publish(ResourceUpdated(uri="note://todo"))
            await reads.wait_for(6)
            await stream.wait_for(3)
            assert teed_subscription_id(2) != second_id

            tg.cancel_scope.cancel()
