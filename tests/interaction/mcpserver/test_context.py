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
from tests._stamp import Unstamp
from tests.interaction._connect import Connect
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("mcpserver:context:logging")
@requirement("logging:capability:declared")
async def test_context_logging_helpers_send_log_notifications(connect: Connect) -> None:
    """Each Context logging helper sends a log message notification at the matching severity.

    All four notifications reach the client's logging callback before the tool call returns; none
    of them carry a logger name unless one is passed explicitly. The server emits these without
    advertising the logging capability (see the divergence note on logging:capability).
    """
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
    # The spec requires servers that emit log notifications to declare the logging capability.
    assert advertised_logging is None


@requirement("mcpserver:context:progress")
async def test_context_report_progress_sends_progress_notifications(connect: Connect, unstamped: Unstamp) -> None:
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

    async with connect(mcp) as client:
        result = await client.call_tool("crunch", {}, progress_callback=on_progress)

    assert unstamped(result) == snapshot(
        CallToolResult(content=[TextContent(text="crunched")], structured_content={"result": "crunched"})
    )
    assert received == snapshot([(1.0, 3.0, None), (2.0, 3.0, "halfway there")])


@requirement("mcpserver:tool:extra")
async def test_context_exposes_request_id_and_client_info_to_a_tool(connect: Connect) -> None:
    """A tool can read the per-request id and the connecting client's identity through Context.

    The request id is non-empty (its concrete value depends on transport-level sequencing, so the
    test asserts the value the tool saw is the one returned, rather than pinning the literal); the
    client info reflects what the caller passed to `Client`.
    """
    mcp = MCPServer("introspector")

    @mcp.tool()
    async def whoami(ctx: Context) -> str:
        client_params = ctx.session.client_params
        assert client_params is not None
        return f"request {ctx.request_id} from {client_params.client_info.name} {client_params.client_info.version}"

    async with connect(mcp, client_info=Implementation(name="acme-agent", version="9.9.9")) as client:
        result = await client.call_tool("whoami", {})

    assert isinstance(result.content[0], TextContent)
    text = result.content[0].text
    assert text.startswith("request ")
    assert text.endswith(" from acme-agent 9.9.9")
    request_id = text.removeprefix("request ").removesuffix(" from acme-agent 9.9.9")
    assert request_id


@requirement("mcpserver:context:logging")
@requirement("protocol:progress:no-token")
async def test_report_progress_without_a_progress_token_sends_nothing(connect: Connect, unstamped: Unstamp) -> None:
    """When the caller supplied no progress callback, Context.report_progress is a silent no-op.

    The tool also emits one log message as a sentinel: the message handler receives only that,
    proving the notification pipeline works and no progress notification was sent for the
    token-less request.
    """
    received: list[IncomingMessage] = []
    mcp = MCPServer("quiet")

    @mcp.tool()
    async def mill(ctx: Context) -> str:
        await ctx.report_progress(1, 3)
        await ctx.info("milling done")  # pyright: ignore[reportDeprecated]
        return "milled"

    async def collect(message: IncomingMessage) -> None:
        received.append(message)

    async with connect(mcp, message_handler=collect) as client:
        result = await client.call_tool("mill", {})

    assert unstamped(result) == snapshot(
        CallToolResult(content=[TextContent(text="milled")], structured_content={"result": "milled"})
    )
    assert received == snapshot(
        [LoggingMessageNotification(params=LoggingMessageNotificationParams(level="info", data="milling done"))]
    )


@requirement("mcpserver:context:elicit")
@requirement("tools:call:elicitation-roundtrip")
async def test_context_elicit_returns_typed_result(connect: Connect) -> None:
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
async def test_context_read_resource_reads_registered_resource(connect: Connect, unstamped: Unstamp) -> None:
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

    async with connect(mcp) as client:
        result = await client.call_tool("show_config", {})

    assert unstamped(result) == snapshot(
        CallToolResult(
            content=[TextContent(text="text/plain: 'theme = dark'")],
            structured_content={"result": "text/plain: 'theme = dark'"},
        )
    )


@requirement("logging:message:filtered")
async def test_set_logging_level_is_rejected_and_messages_are_never_filtered(connect: Connect) -> None:
    """MCPServer does not support logging/setLevel, so log messages are never filtered by severity.

    The request is rejected with METHOD_NOT_FOUND because MCPServer registers no handler for it,
    and every message a tool emits is delivered regardless of level. The spec says the server
    should only send messages at or above the configured level; with no way to configure one,
    everything is sent.
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
