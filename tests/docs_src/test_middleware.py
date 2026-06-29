"""`docs/advanced/middleware.md`: every claim the page makes, proved against the real SDK."""

import logging
import re

import pytest
from mcp_types import (
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    CallToolRequestParams,
    ErrorData,
    RequestId,
    TextContent,
)

from docs_src.middleware import tutorial001
from mcp import Client, MCPError
from mcp.server import Server, ServerRequestContext
from mcp.server.context import CallNext, HandlerResult

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


def _is_timing_record(record: logging.LogRecord) -> bool:
    return record.name == tutorial001.logger.name


def test_timing_record_predicate() -> None:
    args = (logging.INFO, __file__, 1, "msg", None, None)
    assert _is_timing_record(logging.LogRecord(tutorial001.logger.name, *args))
    assert not _is_timing_record(logging.LogRecord("somebody.elses.logger", *args))


async def test_middleware_observes_every_inbound_message(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=tutorial001.logger.name):
        async with Client(tutorial001.server) as client:
            await client.list_tools()
            await client.call_tool("search_books", {"query": "dune"})
    messages = [record.getMessage() for record in filter(_is_timing_record, caplog.records)]
    assert [message.split(" took ")[0] for message in messages] == ["server/discover", "tools/list", "tools/call"]
    assert re.fullmatch(r"tools/call took \d+\.\d ms", messages[-1])


async def test_the_result_passes_through_unchanged() -> None:
    async with Client(tutorial001.server) as client:
        result = await client.call_tool("search_books", {"query": "dune"})
        assert not result.is_error
        assert result.content == [TextContent(type="text", text="Found 3 books matching 'dune'.")]


async def test_a_notification_has_no_request_id() -> None:
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
    expected = (
        "'initialize' is handled by the server runner and cannot be overridden; "
        "use Server.middleware to observe or wrap initialization"
    )
    with pytest.raises(ValueError, match=re.escape(expected)):
        tutorial001.server.add_request_handler("initialize", CallToolRequestParams, tutorial001.on_call_tool)
