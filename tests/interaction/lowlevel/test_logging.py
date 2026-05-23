"""Logging interactions against the low-level Server, driven through the public Client API.

Notification ordering: the in-memory transport delivers every server-to-client message on one
ordered stream, and the client's receive loop dispatches each incoming message to completion
before reading the next one. Together these guarantee that every notification the server sends
before its response reaches the client callback before the originating request returns, so tests
collect notifications into a plain list and assert after the request completes -- no events, no
waiting. This does not generalise to transports that split messages across streams (the
streamable HTTP standalone GET stream); tests over those transports must synchronise explicitly.
"""

import pytest
from inline_snapshot import snapshot

from mcp import types
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import CallToolResult, EmptyResult, LoggingMessageNotificationParams, TextContent
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
async def test_set_logging_level_reaches_handler() -> None:
    """The level requested by the client is delivered to the server's handler verbatim."""

    async def set_logging_level(ctx: ServerRequestContext, params: types.SetLevelRequestParams) -> EmptyResult:
        assert params.level == "warning"
        return EmptyResult()

    server = Server("logger", on_set_logging_level=set_logging_level)

    async with Client(server) as client:
        result = await client.set_logging_level("warning")

    assert result == snapshot(EmptyResult())


@requirement("logging:message:notification")
async def test_log_messages_reach_logging_callback_in_order() -> None:
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
        await ctx.session.send_log_message(level="info", data="starting up", logger="app.lifecycle")
        await ctx.session.send_log_message(level="error", data={"code": 502, "retryable": True})
        return CallToolResult(content=[TextContent(text="done")])

    server = Server("logger", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server, logging_callback=collect) as client:
        result = await client.call_tool("chatty", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="done")]))
    assert received == snapshot(
        [
            LoggingMessageNotificationParams(level="info", logger="app.lifecycle", data="starting up"),
            LoggingMessageNotificationParams(level="error", data={"code": 502, "retryable": True}),
        ]
    )


@requirement("logging:message:all-levels")
async def test_log_messages_at_every_severity_level() -> None:
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
            await ctx.session.send_log_message(level=level, data=f"a {level} message")
        return CallToolResult(content=[TextContent(text="logged")])

    server = Server("logger", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server, logging_callback=collect) as client:
        await client.call_tool("siren", {})

    assert [params.level for params in received] == list(ALL_LEVELS)
