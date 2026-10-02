"""`docs/handlers/cancellation.md`: every claim the page makes, proved against the real SDK."""

import threading
from collections.abc import Awaitable, Callable

import anyio
import anyio.from_thread
import pytest
from mcp_types import REQUEST_TIMEOUT

from docs_src.cancellation import tutorial001, tutorial002
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from tests.interaction._connect import BASE_URL, mounted_app

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]

# "auto" dispatches in process; "legacy" puts a JSON-RPC stream, and so a cancellation message, in between.
both_connections = pytest.mark.parametrize("mode", ["auto", "legacy"])

TITLES = ["Dune", "Emma", "Ulysses"]


async def abandon(
    call: Callable[[], Awaitable[object]], started: anyio.Event, then: Callable[[], object] = lambda: None
) -> None:
    """Start `call`, cancel the task awaiting it once `started` is set, let the server settle, then run `then`."""
    scope = anyio.CancelScope()

    async def doomed() -> None:
        with scope:
            await call()
            raise NotImplementedError  # unreachable: the call never resolves

    async with anyio.create_task_group() as tg:
        tg.start_soon(doomed)
        await started.wait()
        scope.cancel()
        await anyio.wait_all_tasks_blocked()
        then()


@pytest.fixture
def payment_started(monkeypatch: pytest.MonkeyPatch) -> anyio.Event:
    """Replace tutorial001's `take_payment` with one that says the tool reached it and then never finishes."""
    started = anyio.Event()

    async def take_payment(title: str) -> None:
        assert title in tutorial001.holds
        started.set()
        await anyio.sleep_forever()

    monkeypatch.setattr(tutorial001, "take_payment", take_payment)
    return started


@pytest.fixture
def hold_released(monkeypatch: pytest.MonkeyPatch) -> anyio.Event:
    """Wrap tutorial001's own `release_hold` so the test can wait for it to reach its last line."""
    released = anyio.Event()
    release_hold = tutorial001.release_hold

    async def announcing_release_hold(title: str) -> None:
        await release_hold(title)
        released.set()

    monkeypatch.setattr(tutorial001, "release_hold", announcing_release_hold)
    return released


@both_connections
async def test_abandoning_the_call_runs_the_shielded_cleanup_to_the_end(
    mode: str, payment_started: anyio.Event, hold_released: anyio.Event
) -> None:
    """tutorial001: the client gives up mid-payment, and the `finally` still awaits `release_hold` to completion."""
    with anyio.fail_after(5):
        async with Client(tutorial001.mcp, mode=mode) as client:
            await abandon(lambda: client.call_tool("order_book", {"title": "Dune"}), payment_started)
            await hold_released.wait()
    assert tutorial001.holds == set()


@pytest.mark.parametrize("mode", ["2026-07-28", "legacy"])
async def test_abandoning_the_call_over_streamable_http_runs_the_cleanup_too(
    mode: str, payment_started: anyio.Event, hold_released: anyio.Event
) -> None:
    """The last section: with the default options, either era's way of cancelling over HTTP reaches tutorial001."""
    with anyio.fail_after(5):
        async with (
            mounted_app(tutorial001.mcp) as (http, _),
            Client(streamable_http_client(f"{BASE_URL}/mcp", http_client=http), mode=mode) as client,
        ):
            await abandon(lambda: client.call_tool("order_book", {"title": "Dune"}), payment_started)
            await hold_released.wait()
            # Let the legacy transport's late answer to the abandoned call land while the client is still open.
            await anyio.wait_all_tasks_blocked()
    assert tutorial001.holds == set()


@both_connections
async def test_a_client_timeout_cancels_the_tool_the_same_way(
    mode: str, payment_started: anyio.Event, hold_released: anyio.Event
) -> None:
    """The last section: `read_timeout_seconds` running out is the other way this SDK's client gives up."""
    with anyio.fail_after(5):
        async with Client(tutorial001.mcp, mode=mode) as client:
            with pytest.raises(MCPError) as exc_info:
                # The tool never answers, so any positive timeout expires; this one adds no wall-clock time.
                await client.call_tool("order_book", {"title": "Dune"}, read_timeout_seconds=0.000001)
            await hold_released.wait()
    assert exc_info.value.error.code == REQUEST_TIMEOUT
    assert payment_started.is_set()
    assert tutorial001.holds == set()


@both_connections
async def test_check_cancelled_stops_a_def_tool_at_its_next_check(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """tutorial002: cancelled during the first book, the loop raises at its next check and the `finally` cleans up."""
    started = anyio.Event()
    resume = threading.Event()
    indexed: list[str] = []

    def index_book(title: str) -> None:
        assert tutorial002.offline == {"search"}
        indexed.append(title)
        anyio.from_thread.run_sync(started.set)
        assert resume.wait(5)

    monkeypatch.setattr(tutorial002, "index_book", index_book)
    with anyio.fail_after(5):
        # Leaving the block waits for the tool's thread, so what it left behind is final after it.
        async with Client(tutorial002.mcp, mode=mode) as client:
            await abandon(lambda: client.call_tool("rebuild_index", {"titles": TITLES}), started, then=resume.set)
    assert indexed == ["Dune"]
    assert tutorial002.offline == set()


async def test_a_def_tool_nobody_cancels_indexes_every_book_and_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """tutorial002: while the call is live the checks do nothing, and the `finally` runs on a normal finish too."""
    indexed: list[str] = []
    monkeypatch.setattr(tutorial002, "index_book", indexed.append)
    async with Client(tutorial002.mcp) as client:
        result = await client.call_tool("rebuild_index", {"titles": TITLES})
    assert result.structured_content == {"result": "Indexed 3 books."}
    assert indexed == TITLES
    assert tutorial002.offline == set()


async def test_a_def_tool_that_never_checks_runs_to_the_end() -> None:
    """The `def` section's last bullet: nothing interrupts the thread, so the tool outlives its own cancellation."""
    started = anyio.Event()
    resume = threading.Event()
    finished: list[str] = []
    mcp = MCPServer("Bookshop")

    @mcp.tool()
    def rebuild_index() -> str:
        anyio.from_thread.run_sync(started.set)
        assert resume.wait(5)
        finished.append("rebuild_index")
        return "Indexed 3 books."

    with anyio.fail_after(5):
        async with Client(mcp, mode="legacy") as client:
            await abandon(lambda: client.call_tool("rebuild_index", {}), started, then=resume.set)
    assert finished == ["rebuild_index"]


async def test_prompt_and_resource_functions_are_cancelled_like_tools() -> None:
    """The last section: a prompt or a resource function parked on an `await` is cancelled when the client gives up."""
    started = {"blurb": anyio.Event(), "stock": anyio.Event()}
    cancelled = {"blurb": anyio.Event(), "stock": anyio.Event()}
    mcp = MCPServer("Bookshop")

    async def park(name: str) -> str:
        started[name].set()
        try:
            await anyio.sleep_forever()
        finally:
            cancelled[name].set()
        raise NotImplementedError  # unreachable: only cancellation ends the sleep

    @mcp.prompt()
    async def blurb() -> str:
        return await park("blurb")

    @mcp.resource("stock://all")
    async def stock() -> str:
        return await park("stock")

    with anyio.fail_after(5):
        async with Client(mcp, mode="legacy") as client:
            await abandon(lambda: client.get_prompt("blurb"), started["blurb"])
            await cancelled["blurb"].wait()
            await abandon(lambda: client.read_resource("stock://all"), started["stock"])
            await cancelled["stock"].wait()


@pytest.mark.parametrize(
    ("json_response", "stateless_http", "mode"),
    [(True, False, "2026-07-28"), (False, True, "legacy")],
    ids=["json_response-modern", "stateless_http-legacy"],
)
async def test_two_http_options_keep_the_cancellation_from_the_handler(
    json_response: bool, stateless_http: bool, mode: str
) -> None:
    """The `!!! warning`: on these two pairings the abandoned tool is still there once everything has settled.

    Pins known gaps. A stateless legacy server has no session in which to find the request that
    `notifications/cancelled` names. In JSON-response mode the 2026-07-28 entry does not watch for
    the disconnect that is that revision's cancellation signal; if that arm starts timing out, the
    gap was closed and the warning should lose that half.
    """
    started = anyio.Event()
    resume = anyio.Event()
    finished = anyio.Event()
    mcp = MCPServer("Bookshop")

    @mcp.tool()
    async def order_book() -> str:
        started.set()
        await resume.wait()
        finished.set()
        return "Ordered."

    with anyio.fail_after(5):
        async with (
            mounted_app(mcp, json_response=json_response, stateless_http=stateless_http) as (http, _),
            Client(streamable_http_client(f"{BASE_URL}/mcp", http_client=http), mode=mode) as client,
        ):
            await abandon(lambda: client.call_tool("order_book", {}), started, then=resume.set)
            await finished.wait()
