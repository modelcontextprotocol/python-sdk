"""The Context convenience methods MCPServer injects into tool functions, observed from the client."""

import pytest
from inline_snapshot import snapshot
from mcp_types import (
    METHOD_NOT_FOUND,
    CallToolResult,
    ElicitRequestFormParams,
    ElicitRequestParams,
    ElicitResult,
    ErrorData,
    Implementation,
    LoggingMessageNotification,
    LoggingMessageNotificationParams,
    TextContent,
)
from pydantic import BaseModel

from mcp import MCPError
from mcp.client import ClientRequestContext
from mcp.server.elicitation import AcceptedElicitation
from mcp.server.mcpserver import Context, MCPServer
from tests.interaction._connect import Connect
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("mcpserver:context:logging")
@requirement("logging:capability:declared")
async def test_context_logging_helpers_send_log_notifications(connect: Connect) -> None:
    received: list[LoggingMessageNotificationParams] = []
    mcp = MCPServer("chatty")

    @mcp.tool()
    async def narrate(ctx: Context) -> str:
        await ctx.debug("d")  # pyright: ignore[reportDeprecated]
        await ctx.info("i")  # pyright: ignore[reportDeprecated]
        await ctx.warning("w")  # pyright: ignore[reportDeprecated]
        await ctx.error("e")  # pyright: ignore[reportDeprecated]
        return "done"

    async def collect(params: LoggingMessageNotificationParams) -> None:
        received.append(params)

    async with connect(mcp, logging_callback=collect) as client:
        result = await client.call_tool("narrate", {})
        advertised_logging = client.server_capabilities.logging

    assert result == snapshot(CallToolResult(content=[TextContent(text="done")], structured_content={"result": "done"}))
    assert received == snapshot(
        [
            LoggingMessageNotificationParams(level="debug", data="d"),
            LoggingMessageNotificationParams(level="info", data="i"),
            LoggingMessageNotificationParams(level="warning", data="w"),
            LoggingMessageNotificationParams(level="error", data="e"),
        ]
    )
    # Divergence: the spec requires servers emitting log notifications to declare the logging capability
    # (see the logging:capability divergence note).
    assert advertised_logging is None


@requirement("mcpserver:context:progress")
async def test_context_report_progress_sends_progress_notifications(connect: Connect) -> None:
    received: list[tuple[float, float | None, str | None]] = []
    mcp = MCPServer("worker")

    @mcp.tool()
    async def crunch(ctx: Context) -> str:
        await ctx.report_progress(1, 3)
        await ctx.report_progress(2, 3, "halfway there")
        return "crunched"

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        received.append((progress, total, message))

    async with connect(mcp) as client:
        result = await client.call_tool("crunch", {}, progress_callback=on_progress)

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="crunched")], structured_content={"result": "crunched"})
    )
    assert received == snapshot([(1.0, 3.0, None), (2.0, 3.0, "halfway there")])


@requirement("mcpserver:tool:extra")
async def test_context_exposes_request_id_and_client_info_to_a_tool(connect: Connect) -> None:
    mcp = MCPServer("introspector")

    @mcp.tool()
    async def whoami(ctx: Context) -> str:
        client_params = ctx.session.client_params
        assert client_params is not None
        return f"request {ctx.request_id} from {client_params.client_info.name} {client_params.client_info.version}"

    async with connect(mcp, client_info=Implementation(name="acme-agent", version="9.9.9")) as client:
        result = await client.call_tool("whoami", {})

    # The request id depends on transport-level sequencing, so assert the value the tool saw rather than a literal.
    assert isinstance(result.content[0], TextContent)
    text = result.content[0].text
    assert text.startswith("request ")
    assert text.endswith(" from acme-agent 9.9.9")
    request_id = text.removeprefix("request ").removesuffix(" from acme-agent 9.9.9")
    assert request_id


@requirement("mcpserver:context:logging")
@requirement("protocol:progress:no-token")
async def test_report_progress_without_a_progress_token_sends_nothing(connect: Connect) -> None:
    received: list[IncomingMessage] = []
    mcp = MCPServer("quiet")

    @mcp.tool()
    async def mill(ctx: Context) -> str:
        await ctx.report_progress(1, 3)
        # Sentinel: receiving only this log message proves the pipeline works and no progress notification was sent.
        await ctx.info("milling done")  # pyright: ignore[reportDeprecated]
        return "milled"

    async def collect(message: IncomingMessage) -> None:
        received.append(message)

    async with connect(mcp, message_handler=collect) as client:
        result = await client.call_tool("mill", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="milled")], structured_content={"result": "milled"})
    )
    assert received == snapshot(
        [LoggingMessageNotification(params=LoggingMessageNotificationParams(level="info", data="milling done"))]
    )


@requirement("mcpserver:context:elicit")
@requirement("tools:call:elicitation-roundtrip")
async def test_context_elicit_returns_typed_result(connect: Connect) -> None:
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

    async with connect(mcp, elicitation_callback=answer_form) as client:
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
async def test_context_read_resource_reads_registered_resource(connect: Connect) -> None:
    mcp = MCPServer("library")

    @mcp.resource("config://app")
    def app_config() -> str:
        """The application configuration."""
        return "theme = dark"

    @mcp.tool()
    async def show_config(ctx: Context) -> str:
        contents = list(await ctx.read_resource("config://app"))
        return "\n".join(f"{item.mime_type}: {item.content!r}" for item in contents)

    async with connect(mcp) as client:
        result = await client.call_tool("show_config", {})

    assert result == snapshot(
        CallToolResult(
            content=[TextContent(text="text/plain: 'theme = dark'")],
            structured_content={"result": "text/plain: 'theme = dark'"},
        )
    )


@requirement("logging:message:filtered")
async def test_set_logging_level_is_rejected_and_messages_are_never_filtered(connect: Connect) -> None:
    """MCPServer registers no logging/setLevel handler, so messages are never filtered by severity.

    With no way to configure a level, the spec's at-or-above-configured-level filtering never
    applies: every message a tool emits is delivered.
    """
    received: list[LoggingMessageNotificationParams] = []
    mcp = MCPServer("unfilterable")

    @mcp.tool()
    async def chatter(ctx: Context) -> str:
        await ctx.debug("noise")  # pyright: ignore[reportDeprecated]
        await ctx.error("signal")  # pyright: ignore[reportDeprecated]
        return "done"

    async def collect(params: LoggingMessageNotificationParams) -> None:
        received.append(params)

    async with connect(mcp, logging_callback=collect) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.set_logging_level("error")  # pyright: ignore[reportDeprecated]

        await client.call_tool("chatter", {})

    assert exc_info.value.error == snapshot(
        ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="logging/setLevel")
    )
    assert received == snapshot(
        [
            LoggingMessageNotificationParams(level="debug", data="noise"),
            LoggingMessageNotificationParams(level="error", data="signal"),
        ]
    )
