"""The Context convenience methods MCPServer injects into tool functions, observed from the client."""

import pytest
from inline_snapshot import snapshot
from pydantic import BaseModel

from mcp.client import ClientRequestContext
from mcp.client.client import Client
from mcp.server.elicitation import AcceptedElicitation
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import (
    CallToolResult,
    ElicitRequestFormParams,
    ElicitRequestParams,
    ElicitResult,
    LoggingMessageNotificationParams,
    TextContent,
)
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("mcpserver:context:logging")
async def test_context_logging_helpers_send_log_notifications() -> None:
    """Each Context logging helper sends a log message notification at the matching severity.

    All four notifications reach the client's logging callback before the tool call returns; none
    of them carry a logger name unless one is passed explicitly.
    """
    received: list[LoggingMessageNotificationParams] = []
    mcp = MCPServer("chatty")

    @mcp.tool()
    async def narrate(ctx: Context) -> str:
        await ctx.debug("d")
        await ctx.info("i")
        await ctx.warning("w")
        await ctx.error("e")
        return "done"

    async def collect(params: LoggingMessageNotificationParams) -> None:
        received.append(params)

    async with Client(mcp, logging_callback=collect) as client:
        result = await client.call_tool("narrate", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="done")], structured_content={"result": "done"}))
    assert received == snapshot(
        [
            LoggingMessageNotificationParams(level="debug", data="d"),
            LoggingMessageNotificationParams(level="info", data="i"),
            LoggingMessageNotificationParams(level="warning", data="w"),
            LoggingMessageNotificationParams(level="error", data="e"),
        ]
    )


@requirement("mcpserver:context:progress")
async def test_context_report_progress_sends_progress_notifications() -> None:
    """Context.report_progress sends progress notifications correlated to the calling request.

    The caller's progress callback receives each report, in order, before the tool call returns.
    """
    received: list[tuple[float, float | None, str | None]] = []
    mcp = MCPServer("worker")

    @mcp.tool()
    async def crunch(ctx: Context) -> str:
        await ctx.report_progress(1, 3)
        await ctx.report_progress(2, 3, "halfway there")
        return "crunched"

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        received.append((progress, total, message))

    async with Client(mcp) as client:
        result = await client.call_tool("crunch", {}, progress_callback=on_progress)

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="crunched")], structured_content={"result": "crunched"})
    )
    assert received == snapshot([(1.0, 3.0, None), (2.0, 3.0, "halfway there")])


@requirement("mcpserver:context:elicit")
async def test_context_elicit_returns_typed_result() -> None:
    """Context.elicit sends a form elicitation built from a pydantic schema and returns a typed result.

    The client sees the JSON schema generated from the model; the accepted content is validated
    back into the model and handed to the tool as result.data.
    """
    received: list[ElicitRequestParams] = []
    mcp = MCPServer("travel")

    class TravelPreferences(BaseModel):
        destination: str
        window_seat: bool

    @mcp.tool()
    async def book_flight(ctx: Context) -> str:
        answer = await ctx.elicit("Where to?", TravelPreferences)
        assert isinstance(answer, AcceptedElicitation)
        return f"{answer.action}: {answer.data.destination} window={answer.data.window_seat}"

    async def answer_form(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        received.append(params)
        return ElicitResult(action="accept", content={"destination": "Lisbon", "window_seat": True})

    async with Client(mcp, elicitation_callback=answer_form) as client:
        result = await client.call_tool("book_flight", {})

    assert received == snapshot(
        [
            ElicitRequestFormParams(
                _meta={},
                message="Where to?",
                requested_schema={
                    "properties": {
                        "destination": {"title": "Destination", "type": "string"},
                        "window_seat": {"title": "Window Seat", "type": "boolean"},
                    },
                    "required": ["destination", "window_seat"],
                    "title": "TravelPreferences",
                    "type": "object",
                },
            )
        ]
    )
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(text="accept: Lisbon window=True")],
            structured_content={"result": "accept: Lisbon window=True"},
        )
    )


@requirement("mcpserver:context:read-resource")
async def test_context_read_resource_reads_registered_resource() -> None:
    """Context.read_resource lets a tool read a resource registered on the same server.

    The tool reports the MIME type and content it read, proving the resource function ran and its
    return value came back through the context.
    """
    mcp = MCPServer("library")

    @mcp.resource("config://app")
    def app_config() -> str:
        """The application configuration."""
        return "theme = dark"

    @mcp.tool()
    async def show_config(ctx: Context) -> str:
        contents = list(await ctx.read_resource("config://app"))
        return "\n".join(f"{item.mime_type}: {item.content!r}" for item in contents)

    async with Client(mcp) as client:
        result = await client.call_tool("show_config", {})

    assert result == snapshot(
        CallToolResult(
            content=[TextContent(text="text/plain: 'theme = dark'")],
            structured_content={"result": "text/plain: 'theme = dark'"},
        )
    )
