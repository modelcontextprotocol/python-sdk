"""Logging interactions against the low-level Server, driven through the public Client API.

Notification ordering: await-free callbacks finish in arrival order, and passing
``related_request_id`` keeps each notification on the originating request's POST stream over
streamable HTTP, so plain-list collection is deterministic on every transport leg.
"""

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_PARAMS,
    LOG_LEVEL_META_KEY,
    CallToolResult,
    EmptyResult,
    LoggingMessageNotificationParams,
    TextContent,
)

from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from tests._stamp import Unstamp
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio

ALL_LEVELS: tuple[types.LoggingLevel, ...] = (
    "debug",
    "info",
    "notice",
    "warning",
    "error",
    "critical",
    "alert",
    "emergency",
)


@requirement("logging:set-level")
async def test_set_logging_level_reaches_handler(connect: Connect) -> None:
    """The level requested by the client is delivered to the server's handler verbatim."""

    async def set_logging_level(ctx: ServerRequestContext, params: types.SetLevelRequestParams) -> EmptyResult:
        assert params.level == "warning"
        return EmptyResult()

    server = Server("logger", on_set_logging_level=set_logging_level)  # pyright: ignore[reportDeprecated]

    async with connect(server) as client:
        result = await client.set_logging_level("warning")  # pyright: ignore[reportDeprecated]

    assert result == snapshot(EmptyResult())


@requirement("logging:message:fields")
@requirement("tools:call:logging-mid-execution")
async def test_log_messages_reach_logging_callback_in_order(connect: Connect, unstamped: Unstamp) -> None:
    """Log messages sent during a tool call arrive at the logging callback, in order, before the call returns.

    The two messages pin the full notification shape: severity, optional logger name, and both
    string and structured data payloads.
    """
    received: list[LoggingMessageNotificationParams] = []

    async def collect(params: LoggingMessageNotificationParams) -> None:
        received.append(params)

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="chatty", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "chatty"
        await ctx.session.send_log_message(  # pyright: ignore[reportDeprecated]
            level="info", data="starting up", logger="app.lifecycle", related_request_id=ctx.request_id
        )
        await ctx.session.send_log_message(  # pyright: ignore[reportDeprecated]
            level="error", data={"code": 502, "retryable": True}, related_request_id=ctx.request_id
        )
        return CallToolResult(content=[TextContent(text="done")])

    async def set_logging_level(ctx: ServerRequestContext, params: types.SetLevelRequestParams) -> EmptyResult:
        """Registered so the logging capability is advertised; the client never sets a level."""
        raise NotImplementedError

    server = Server(  # pyright: ignore[reportDeprecated]
        "logger", on_list_tools=list_tools, on_call_tool=call_tool, on_set_logging_level=set_logging_level
    )

    async with connect(server, logging_callback=collect, log_level="debug") as client:
        result = await client.call_tool("chatty", {})

    assert unstamped(result) == snapshot(CallToolResult(content=[TextContent(text="done")]))
    assert received == snapshot(
        [
            LoggingMessageNotificationParams(level="info", logger="app.lifecycle", data="starting up"),
            LoggingMessageNotificationParams(level="error", data={"code": 502, "retryable": True}),
        ]
    )


@requirement("logging:message:all-levels")
async def test_log_messages_at_every_severity_level(connect: Connect) -> None:
    """Each of the eight RFC 5424 severity levels is deliverable as a log message notification."""
    received: list[LoggingMessageNotificationParams] = []

    async def collect(params: LoggingMessageNotificationParams) -> None:
        received.append(params)

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="siren", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "siren"
        for level in ALL_LEVELS:
            await ctx.session.send_log_message(  # pyright: ignore[reportDeprecated]
                level=level, data=f"a {level} message", related_request_id=ctx.request_id
            )
        return CallToolResult(content=[TextContent(text="logged")])

    async def set_logging_level(ctx: ServerRequestContext, params: types.SetLevelRequestParams) -> EmptyResult:
        """Registered so the logging capability is advertised; the client never sets a level."""
        raise NotImplementedError

    server = Server(  # pyright: ignore[reportDeprecated]
        "logger", on_list_tools=list_tools, on_call_tool=call_tool, on_set_logging_level=set_logging_level
    )

    async with connect(server, logging_callback=collect, log_level="debug") as client:
        await client.call_tool("siren", {})

    assert [params.level for params in received] == list(ALL_LEVELS)


def _siren_server() -> Server:
    """A server whose `siren` tool logs one message at each of the eight severity levels.

    The messages are sent without `related_request_id`: on 2026-07-28+ log delivery is
    request-scoped by construction, so they still ride the requesting stream on every leg.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="siren", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "siren"
        for level in ALL_LEVELS:
            await ctx.session.send_log_message(level=level, data=f"a {level} message")  # pyright: ignore[reportDeprecated]
        return CallToolResult(content=[TextContent(text="logged")])

    return Server("logger", on_list_tools=list_tools, on_call_tool=call_tool)


@requirement("logging:per-request:opt-in")
@requirement("logging:per-request:threshold")
async def test_log_delivery_follows_the_per_request_log_level(connect: Connect) -> None:
    """Without io.modelcontextprotocol/logLevel in _meta a request gets no log messages;
    with it, only entries at or above the requested level are delivered, in order.

    The handler emits at every severity in both phases: the un-opted request receives
    nothing (the log calls are dropped, not delivered on some other stream), and the request
    opting in at `warning` receives warning and above.
    """
    received: list[types.LoggingLevel] = []

    async def collect(params: LoggingMessageNotificationParams) -> None:
        received.append(params.level)

    async with connect(_siren_server(), logging_callback=collect) as client:
        result = await client.call_tool("siren", {})
    assert isinstance(result.content[0], TextContent) and result.content[0].text == "logged"
    assert received == []

    async with connect(_siren_server(), logging_callback=collect, log_level="warning") as client:
        await client.call_tool("siren", {})
    assert received == ["warning", "error", "critical", "alert", "emergency"]


@requirement("logging:per-request:invalid-level")
async def test_a_request_with_an_unrecognized_log_level_is_rejected(connect: Connect) -> None:
    """A request whose _meta names an unrecognized log level is rejected with -32602 before the handler runs."""
    async with connect(_siren_server()) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("siren", {}, meta={LOG_LEVEL_META_KEY: "verbose"})

    assert exc_info.value.error.code == INVALID_PARAMS
