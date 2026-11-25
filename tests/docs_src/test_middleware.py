"""`docs/advanced/middleware.md`: every claim the page makes, proved against the real SDK."""

import logging
import re

import anyio
import pytest
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    CallToolRequestParams,
    CallToolResult,
    ErrorData,
    RequestId,
    TextContent,
)

from docs_src.middleware import tutorial001, tutorial002
from mcp import Client, MCPError
from mcp.server import Server, ServerRequestContext
from mcp.server.context import CallNext, HandlerResult

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


def _is_timing_record(record: logging.LogRecord) -> bool:
    """A record emitted by tutorial001's `log_timing` middleware (and nothing else caplog caught)."""
    return record.name == tutorial001.logger.name


class _HeldSearches:
    """An `on_call_tool` for `search_books` that holds each call open until the test finishes it, keyed by query.

    A query the test did not name is a `KeyError`: a call the cap should have refused cannot quietly succeed.
    """

    def __init__(self, *queries: str) -> None:
        self.started = {query: anyio.Event() for query in queries}
        self.finish = {query: anyio.Event() for query in queries}

    async def __call__(self, ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "search_books"
        query = (params.arguments or {})["query"]
        self.started[query].set()
        await self.finish[query].wait()
        return CallToolResult(content=[TextContent(type="text", text=f"Found {query}.")])


async def _search(client: Client, query: str, results: dict[str, CallToolResult]) -> None:
    """Call `search_books` and file the result under its query, for calls a test runs in the background."""
    results[query] = await client.call_tool("search_books", {"query": query})


def test_timing_record_predicate() -> None:
    """The caplog filter keeps the middleware's own records and drops everyone else's."""
    args = (logging.INFO, __file__, 1, "msg", None, None)
    assert _is_timing_record(logging.LogRecord(tutorial001.logger.name, *args))
    assert not _is_timing_record(logging.LogRecord("somebody.elses.logger", *args))


async def test_middleware_observes_every_inbound_message(caplog: pytest.LogCaptureFixture) -> None:
    """tutorial001: two client calls produce three timed lines. `server/discover` is wrapped too."""
    with caplog.at_level(logging.INFO, logger=tutorial001.logger.name):
        async with Client(tutorial001.server) as client:
            await client.list_tools()
            await client.call_tool("search_books", {"query": "dune"})
    messages = [record.getMessage() for record in filter(_is_timing_record, caplog.records)]
    assert [message.split(" took ")[0] for message in messages] == ["server/discover", "tools/list", "tools/call"]
    assert re.fullmatch(r"tools/call took \d+\.\d ms", messages[-1])


async def test_the_result_passes_through_unchanged() -> None:
    """tutorial001: `log_timing` returns what `call_next` returned, so the client sees the real result."""
    async with Client(tutorial001.server) as client:
        result = await client.call_tool("search_books", {"query": "dune"})
        assert not result.is_error
        assert result.content == [TextContent(type="text", text="Found 3 books matching 'dune'.")]


async def test_a_notification_has_no_request_id() -> None:
    """`ctx.request_id is None` is how middleware tells a notification from a request."""
    seen: list[tuple[str, RequestId | None]] = []

    async def spy(ctx: ServerRequestContext, call_next: CallNext) -> HandlerResult:
        seen.append((ctx.method, ctx.request_id))
        return await call_next(ctx)

    server = Server("Bookshop", on_list_tools=tutorial001.on_list_tools, on_call_tool=tutorial001.on_call_tool)
    server.middleware.append(spy)
    async with Client(server, mode="legacy") as client:
        await client.list_tools()
    assert seen == [("initialize", 1), ("notifications/initialized", None), ("tools/list", 2)]


async def test_raising_before_call_next_refuses_the_message() -> None:
    """A middleware that raises instead of calling `call_next` answers with a JSON-RPC error."""

    async def gate(ctx: ServerRequestContext, call_next: CallNext) -> HandlerResult:
        if ctx.method == "tools/call":
            raise MCPError(code=INVALID_REQUEST, message="No calls on Sundays.")
        return await call_next(ctx)

    server = Server("Bookshop", on_list_tools=tutorial001.on_list_tools, on_call_tool=tutorial001.on_call_tool)
    server.middleware.append(gate)
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("search_books", {"query": "dune"})
        assert exc_info.value.error.code == INVALID_REQUEST
        assert exc_info.value.error.message == "No calls on Sundays."
        assert len((await client.list_tools()).tools) == 1


async def test_an_unhandled_method_raises_through_the_middleware() -> None:
    """A method without a handler raises `METHOD_NOT_FOUND` out of `call_next`, through the middleware."""
    seen: list[tuple[str, int]] = []

    async def spy(ctx: ServerRequestContext, call_next: CallNext) -> HandlerResult:
        try:
            return await call_next(ctx)
        except MCPError as exc:
            seen.append((ctx.method, exc.error.code))
            raise

    server = Server("Bookshop", on_list_tools=tutorial001.on_list_tools, on_call_tool=tutorial001.on_call_tool)
    server.middleware.append(spy)
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("config://settings")
    assert exc_info.value.error == ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="resources/read")
    assert seen == [("resources/read", METHOD_NOT_FOUND)]


async def test_initialize_cannot_be_replaced_only_wrapped() -> None:
    """`add_request_handler("initialize", ...)` is rejected: middleware is the sanctioned hook."""
    expected = (
        "'initialize' is handled by the server runner and cannot be overridden; "
        "use Server.middleware to observe or wrap initialization"
    )
    with pytest.raises(ValueError, match=re.escape(expected)):
        tutorial001.server.add_request_handler("initialize", CallToolRequestParams, tutorial001.on_call_tool)


async def test_a_tool_call_over_the_cap_is_refused_while_the_earlier_calls_still_run() -> None:
    """tutorial002: with `limit` tool calls in flight, the next one is answered with the busy error at once.

    Steps:
    1. One client's four calls enter the handler and are held there.
    2. A second client connects (its `server/discover` is not a tool call) and makes a fifth call, which is
       refused before any of the four has returned: the count belongs to the server, not to a connection.
    3. The four are finished and each returns its own result.
    """
    held = _HeldSearches("dune", "emma", "ulysses", "walden")
    server = Server("Bookshop", on_list_tools=tutorial002.on_list_tools, on_call_tool=held)
    server.middleware.append(tutorial002.max_concurrent_tool_calls(4))
    results: dict[str, CallToolResult] = {}
    with anyio.fail_after(5):
        async with Client(server) as client:
            async with anyio.create_task_group() as tg:
                for query in held.started:
                    tg.start_soon(_search, client, query, results)
                for started in held.started.values():
                    await started.wait()
                async with Client(server) as latecomer:
                    with pytest.raises(MCPError) as exc_info:
                        await latecomer.call_tool("search_books", {"query": "middlemarch"})
                    assert exc_info.value.error == ErrorData(
                        code=tutorial002.SERVER_BUSY, message="Server busy: tool call limit reached (4 in progress)."
                    )
                    assert results == {}
                for finish in held.finish.values():
                    finish.set()
            assert {query: result.content for query, result in results.items()} == {
                query: [TextContent(type="text", text=f"Found {query}.")] for query in held.started
            }


async def test_other_requests_are_answered_with_the_cap_reached() -> None:
    """tutorial002: only `tools/call` is capped, so `tools/list` is answered with the cap reached."""
    held = _HeldSearches("dune")
    server = Server("Bookshop", on_list_tools=tutorial002.on_list_tools, on_call_tool=held)
    server.middleware.append(tutorial002.max_concurrent_tool_calls(1))
    results: dict[str, CallToolResult] = {}
    with anyio.fail_after(5):
        async with Client(server) as client:
            async with anyio.create_task_group() as tg:
                tg.start_soon(_search, client, "dune", results)
                await held.started["dune"].wait()
                tools = (await client.list_tools()).tools
                assert [tool.name for tool in tools] == ["search_books"]
                assert results == {}
                held.finish["dune"].set()
            assert results["dune"].content == [TextContent(type="text", text="Found dune.")]


async def test_a_refused_call_is_accepted_once_a_running_call_finishes() -> None:
    """tutorial002: a finished call gives its slot back, so the caller that was refused gets through on a retry."""
    held = _HeldSearches("dune", "emma")
    server = Server("Bookshop", on_list_tools=tutorial002.on_list_tools, on_call_tool=held)
    server.middleware.append(tutorial002.max_concurrent_tool_calls(1))
    results: dict[str, CallToolResult] = {}
    # Only `dune` is held open; `emma` returns as soon as it is let in.
    held.finish["emma"].set()
    with anyio.fail_after(5):
        async with Client(server) as client:
            async with anyio.create_task_group() as tg:
                tg.start_soon(_search, client, "dune", results)
                await held.started["dune"].wait()
                with pytest.raises(MCPError) as exc_info:
                    await client.call_tool("search_books", {"query": "emma"})
                assert exc_info.value.error.code == tutorial002.SERVER_BUSY
                assert not held.started["emma"].is_set()
                held.finish["dune"].set()
            # The task group has joined, so the first call's response has arrived.
            retried = await client.call_tool("search_books", {"query": "emma"})
    assert results["dune"].content == [TextContent(type="text", text="Found dune.")]
    assert retried.content == [TextContent(type="text", text="Found emma.")]


async def test_a_tool_call_that_raises_gives_its_slot_back() -> None:
    """tutorial002: the `finally` releases the slot when the handler raises, so the next call is not refused."""

    async def on_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "search_books"
        query = (params.arguments or {})["query"]
        if query == "necronomicon":
            raise RuntimeError("the shelf collapsed")
        return CallToolResult(content=[TextContent(type="text", text=f"Found {query}.")])

    server = Server("Bookshop", on_list_tools=tutorial002.on_list_tools, on_call_tool=on_call_tool)
    server.middleware.append(tutorial002.max_concurrent_tool_calls(1))
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("search_books", {"query": "necronomicon"})
        assert exc_info.value.error.code == INTERNAL_ERROR
        result = await client.call_tool("search_books", {"query": "dune"})
    assert result.content == [TextContent(type="text", text="Found dune.")]


async def test_a_cancelled_tool_call_gives_its_slot_back() -> None:
    """tutorial002: a call the client abandons is cancelled out of `call_next`, and the `finally` frees its slot."""
    started = anyio.Event()
    cancelled = anyio.Event()

    async def on_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "search_books"
        query = (params.arguments or {})["query"]
        if query == "dune":
            started.set()
            try:
                await anyio.sleep_forever()
            finally:
                cancelled.set()
        return CallToolResult(content=[TextContent(type="text", text=f"Found {query}.")])

    server = Server("Bookshop", on_list_tools=tutorial002.on_list_tools, on_call_tool=on_call_tool)
    server.middleware.append(tutorial002.max_concurrent_tool_calls(1))
    results: dict[str, CallToolResult] = {}
    with anyio.fail_after(5):
        async with Client(server) as client:
            async with anyio.create_task_group() as tg:
                tg.start_soon(_search, client, "dune", results)
                await started.wait()
                tg.cancel_scope.cancel()
            await cancelled.wait()
            result = await client.call_tool("search_books", {"query": "emma"})
    assert results == {}
    assert result.content == [TextContent(type="text", text="Found emma.")]


async def test_answering_with_an_error_result_returns_it_to_the_caller_instead_of_raising() -> None:
    """A middleware that answers `tools/call` with an `is_error=True` result gives the client a result, not an error."""

    async def busy(ctx: ServerRequestContext, call_next: CallNext) -> HandlerResult:
        if ctx.method == "tools/call":
            return CallToolResult(
                content=[TextContent(type="text", text="Server busy. Try again shortly.")], is_error=True
            )
        return await call_next(ctx)

    server = Server("Bookshop", on_list_tools=tutorial002.on_list_tools, on_call_tool=tutorial002.on_call_tool)
    server.middleware.append(busy)
    async with Client(server) as client:
        result = await client.call_tool("search_books", {"query": "dune"})
    assert result.is_error
    assert result.content == [TextContent(type="text", text="Server busy. Try again shortly.")]


async def test_calls_made_one_after_another_never_reach_the_cap() -> None:
    """tutorial002's own server: the cap counts calls in flight, so more than four in sequence all succeed."""
    async with Client(tutorial002.server) as client:
        results = [await client.call_tool("search_books", {"query": "dune"}) for _ in range(5)]
    assert [result.content for result in results] == [
        [TextContent(type="text", text="Found 3 books matching 'dune'.")]
    ] * 5
