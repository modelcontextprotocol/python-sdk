"""`docs/handlers/subscriptions.md`: every claim the page makes, proved against the real SDK."""

from collections.abc import Awaitable, Callable
from typing import Any

import anyio
import mcp_types as types
import pytest
from trio.testing import MockClock

from docs_src.subscriptions import (
    tutorial001,
    tutorial002,
    tutorial003,
    tutorial004_anyio,
    tutorial004_asyncio,
    tutorial004_trio,
    tutorial005,
)
from mcp import Client
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.subscriptions import SUBSCRIPTION_ID_META_KEY, ListenHandler, ToolsListChanged

_ReadResource = Callable[
    [ServerRequestContext[Any], types.ReadResourceRequestParams], Awaitable[types.ReadResourceResult]
]

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


class _Reads:
    """Counts server-side resource reads so a test can await the Nth refetch."""

    def __init__(self) -> None:
        self.count = 0
        self._bump = anyio.Event()

    def counting(self, handler: _ReadResource) -> _ReadResource:
        async def counted(
            ctx: ServerRequestContext[Any], params: types.ReadResourceRequestParams
        ) -> types.ReadResourceResult:
            result = await handler(ctx, params)
            self.count += 1
            self._bump.set()
            self._bump = anyio.Event()
            return result

        return counted

    async def wait_for(self, count: int) -> None:
        with anyio.fail_after(5):
            while self.count < count:
                await self._bump.wait()


def _listen_request(**fields: Any) -> types.SubscriptionsListenRequest:
    return types.SubscriptionsListenRequest(
        params=types.SubscriptionsListenRequestParams(notifications=types.SubscriptionFilter(**fields))
    )


@pytest.fixture(autouse=True)
def _fresh_server_state() -> Any:
    """Each test starts from an all-unfinished board and the base tool set.

    The tutorials mutate module state deliberately (that is what publishes events), so the
    board contents and the `enable_reports` registration have to be undone between tests.
    """
    boards = {name: dict(tasks) for name, tasks in tutorial001.BOARDS.items()}
    lowlevel_board = dict(tutorial002.BOARD)
    tools = dict(tutorial001.mcp._tool_manager._tools)  # pyright: ignore[reportPrivateUsage]
    yield
    tutorial001.BOARDS.clear()
    tutorial001.BOARDS.update(boards)
    tutorial002.BOARD.clear()
    tutorial002.BOARD.update(lowlevel_board)
    tutorial001.mcp._tool_manager._tools.clear()  # pyright: ignore[reportPrivateUsage]
    tutorial001.mcp._tool_manager._tools.update(tools)  # pyright: ignore[reportPrivateUsage]


async def test_publishes_reach_the_stream_filtered_and_tagged() -> None:
    """tutorial001: the full arc - ack first, exact-URI filtering, list_changed
    leading to a refreshed tool list, and client-side close."""
    stream = _Stream()
    async with Client(tutorial001.mcp, mode="2026-07-28", message_handler=stream.handler) as client:
        async with anyio.create_task_group() as tg:

            async def listen() -> None:
                await client.session.send_request(
                    _listen_request(tools_list_changed=True, resource_subscriptions=["board://sprint"]),
                    types.SubscriptionsListenResult,
                )

            tg.start_soon(listen)
            await stream.wait_for(1)

            ack = stream.received[0]
            assert isinstance(ack, types.SubscriptionsAcknowledgedNotification)
            assert ack.params.notifications == types.SubscriptionFilter(
                tools_list_changed=True, resource_subscriptions=["board://sprint"]
            )
            assert ack.params.meta is not None and SUBSCRIPTION_ID_META_KEY in ack.params.meta

            # An edit to a URI the stream did not subscribe to stays silent...
            await client.call_tool("complete_task", {"board": "backlog", "task": "tidy docs"})
            # ...and the subscribed URI delivers, tagged with the same subscription id.
            await client.call_tool("complete_task", {"board": "sprint", "task": "design"})
            await stream.wait_for(2)
            updated = stream.received[1]
            assert isinstance(updated, types.ResourceUpdatedNotification)
            assert updated.params.uri == "board://sprint"
            assert updated.params.meta == ack.params.meta

            await client.call_tool("enable_reports", {})
            await stream.wait_for(3)
            assert isinstance(stream.received[2], types.ToolListChangedNotification)

            # The client ends the stream by closing it - cancel the parked request.
            tg.cancel_scope.cancel()

        # The list_changed told us to re-fetch: the new tool is there, and the
        # session outlives the closed stream.
        tools = await client.list_tools()
        assert "sprint_report" in {tool.name for tool in tools.tools}
        contents = (await client.read_resource("board://sprint")).contents[0]
        assert isinstance(contents, types.TextResourceContents)
        assert contents.text == "[x] design\n[ ] build\n[ ] ship"


async def test_publish_with_no_subscribers_is_a_no_op() -> None:
    """tutorial001: publishing to an idle server does nothing and breaks nothing."""
    async with Client(tutorial001.mcp, mode="2026-07-28") as client:
        result = await client.call_tool("complete_task", {"board": "sprint", "task": "design"})
        assert result.is_error is not True


async def test_lowlevel_composition_serves_the_same_stream() -> None:
    """tutorial002: bus + ListenHandler on the lowlevel Server is the same machinery."""
    stream = _Stream()
    async with Client(tutorial002.server, mode="2026-07-28", message_handler=stream.handler) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools.tools] == ["complete_task"]

        async with anyio.create_task_group() as tg:

            async def listen() -> None:
                await client.session.send_request(
                    _listen_request(resource_subscriptions=["board://sprint"]),
                    types.SubscriptionsListenResult,
                )

            tg.start_soon(listen)
            await stream.wait_for(1)

            await client.call_tool("complete_task", {"task": "design"})
            await stream.wait_for(2)
            updated = stream.received[1]
            assert isinstance(updated, types.ResourceUpdatedNotification)
            assert updated.params.uri == "board://sprint"

            # The bus you constructed is also the publish surface outside a
            # request; an unrequested kind never reaches this stream.
            await tutorial002.bus.publish(ToolsListChanged())
            await client.call_tool("complete_task", {"task": "build"})
            await stream.wait_for(3)
            assert isinstance(stream.received[2], types.ResourceUpdatedNotification)

            tg.cancel_scope.cancel()


async def test_follow_board_prints_the_refetched_board_and_the_new_tool_list(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """tutorial003: each event drives a refetch - the board reprints, and a tools change reprints the tool names."""
    async with Client(tutorial001.mcp) as client:
        async with anyio.create_task_group() as tg:
            tg.start_soon(tutorial003.follow_board, client)
            # Let the watcher park on its stream (ack complete) before publishing.
            await anyio.wait_all_tasks_blocked()
            await client.call_tool("complete_task", {"board": "sprint", "task": "design"})
            await anyio.wait_all_tasks_blocked()
            await client.call_tool("enable_reports", {})
            await anyio.wait_all_tasks_blocked()
            tg.cancel_scope.cancel()

    printed = capsys.readouterr().out
    assert "[x] design\n[ ] build\n[ ] ship" in printed
    assert "sprint_report" in printed


EMPTY_BOARD = "[ ] design\n[ ] build\n[ ] ship"
FINISHED_BOARD = "[x] design\n[x] build\n[x] ship"


def _assert_snapshot_then_current_board(printed: str) -> None:
    """The snapshot taken inside the open subscription came first, and the watcher ended up current.

    How many times the watcher printed is deliberately not asserted: identical events that pile up
    unconsumed coalesce, so a fast main flow can turn three completions into one refetch. What the
    stream guarantees is that no change after the acknowledgment is missed.
    """
    assert printed.startswith(EMPTY_BOARD), printed
    assert printed.strip().endswith(FINISHED_BOARD), printed


async def test_the_asyncio_watcher_runs_beside_the_main_flow(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial004 (asyncio tab): run_sprint opens the subscription, snapshots the board, then a watcher
    task reprints it while the main flow keeps calling tools.

    The example connects over HTTP; the in-memory client here is the maintainer-side stand-in."""
    async with Client(tutorial001.mcp) as client:
        await tutorial004_asyncio.run_sprint(client)
    _assert_snapshot_then_current_board(capsys.readouterr().out)


@pytest.mark.parametrize("anyio_backend", [pytest.param("trio", id="trio")])
async def test_the_trio_watcher_runs_beside_the_main_flow(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial004 (trio tab): the same shape as the asyncio tab, with a nursery owning the watcher."""
    async with Client(tutorial001.mcp) as client:
        await tutorial004_trio.run_sprint(client)
    _assert_snapshot_then_current_board(capsys.readouterr().out)


async def test_the_anyio_watcher_runs_beside_the_main_flow(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial004 (anyio tab): the same shape again, with a task group owning the watcher."""
    async with Client(tutorial001.mcp) as client:
        await tutorial004_anyio.run_sprint(client)
    _assert_snapshot_then_current_board(capsys.readouterr().out)


@pytest.mark.parametrize(
    "anyio_backend",
    [pytest.param(("trio", {"clock": MockClock(autojump_threshold=0)}), id="trio-mockclock")],
)
async def test_the_follower_re_listens_after_the_stream_ends(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial005: a graceful server close ends one stream; the loop backs off, re-listens, and refetches.

    Runs on trio's autojumping MockClock so the loop's backoff sleep takes no wall-clock time.
    """
    reads = _Reads()
    handler = ListenHandler(tutorial002.bus)
    server = Server(
        "sprint-board",
        on_read_resource=reads.counting(tutorial002.read_resource),
        on_list_tools=tutorial002.list_tools,
        on_call_tool=tutorial002.call_tool,
        on_subscriptions_listen=handler,
    )

    async with Client(server) as client:
        async with anyio.create_task_group() as tg:
            tg.start_soon(tutorial005.keep_following, client)
            # First stream: the entry refetch reads the board, then an event reads it again.
            await reads.wait_for(1)
            await client.call_tool("complete_task", {"task": "design"})
            await reads.wait_for(2)

            # End that stream gracefully. The loop backs off (the mock clock jumps the
            # sleep), re-listens, and refetches on entry: that is the third read.
            handler.close()
            await reads.wait_for(3)
            await client.call_tool("complete_task", {"task": "build"})
            await reads.wait_for(4)
            tg.cancel_scope.cancel()

    printed = capsys.readouterr().out
    assert "[x] design\n[ ] build" in printed  # first stream, after design
    assert "[x] design\n[x] build" in printed  # second stream, after build
