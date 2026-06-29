"""Tool interactions against MCPServer, driven through the public Client API."""

import logging
from typing import Annotated, Literal

import pytest
from inline_snapshot import snapshot
from mcp_types import (
    URL_ELICITATION_REQUIRED,
    CallToolResult,
    ElicitRequestURLParams,
    ErrorData,
    LoggingMessageNotification,
    LoggingMessageNotificationParams,
    TextContent,
)
from pydantic import BaseModel, Field

from mcp import MCPError
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import UrlElicitationRequiredError
from tests.interaction._connect import Connect
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("tools:call:content:text")
async def test_call_tool_returns_text_content(connect: Connect) -> None:
    """The output schema derived from the return annotation adds matching structuredContent to the result."""
    mcp = MCPServer("adder")

    @mcp.tool()
    def add(a: int, b: int) -> str:
        return str(a + b)

    async with connect(mcp) as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})

    assert result == snapshot(CallToolResult(content=[TextContent(text="5")], structured_content={"result": "5"}))


@requirement("mcpserver:tool:schema-variants")
async def test_complex_parameter_types_are_validated_and_coerced_before_the_tool_runs(connect: Connect) -> None:
    mcp = MCPServer("typed")

    class Point(BaseModel):
        x: int
        y: int

    @mcp.tool()
    def place(mode: Literal["fast", "slow"], point: Point, count: Annotated[int, Field(ge=1, le=10)]) -> str:
        assert isinstance(point, Point)
        return f"{mode} at ({point.x}, {point.y}) x{count}"

    async with connect(mcp) as client:
        result = await client.call_tool("place", {"mode": "fast", "point": {"x": "3", "y": 4}, "count": 5})

    assert result == snapshot(
        CallToolResult(
            content=[TextContent(text="fast at (3, 4) x5")], structured_content={"result": "fast at (3, 4) x5"}
        )
    )


@requirement("mcpserver:tool:handler-throws")
@requirement("mcpserver:output-schema:skip-on-error")
async def test_call_tool_function_exception_becomes_error_result(connect: Connect) -> None:
    """The error result is built before output-schema validation, so the `-> str` schema adds no second failure."""
    mcp = MCPServer("errors")

    @mcp.tool()
    def explode() -> str:
        raise ValueError("boom")

    async with connect(mcp) as client:
        result = await client.call_tool("explode", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="Error executing tool explode: boom")], is_error=True)
    )


@requirement("mcpserver:tool:handler-throws")
async def test_call_tool_tool_error_becomes_error_result(connect: Connect) -> None:
    mcp = MCPServer("errors")

    @mcp.tool()
    def flux() -> str:
        raise ToolError("flux capacitor offline")

    async with connect(mcp) as client:
        result = await client.call_tool("flux", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="Error executing tool flux: flux capacitor offline")], is_error=True)
    )


@requirement("mcpserver:tool:unknown-name")
async def test_call_tool_unknown_name_returns_error_result(connect: Connect) -> None:
    """The spec classifies unknown tools as a protocol error; see the divergence note on the requirement."""
    mcp = MCPServer("errors")

    @mcp.tool()
    def add() -> None:
        """A registered tool; the test calls a different name."""

    async with connect(mcp) as client:
        result = await client.call_tool("nope", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="Unknown tool: nope")], is_error=True))


@requirement("mcpserver:tool:output-schema:model")
@requirement("tools:call:structured-content:text-mirror")
async def test_call_tool_model_return_becomes_structured_content(connect: Connect) -> None:
    mcp = MCPServer("weather")

    class Weather(BaseModel):
        temperature: float
        conditions: str

    @mcp.tool()
    def get_weather() -> Weather:
        return Weather(temperature=22.5, conditions="sunny")

    async with connect(mcp) as client:
        listed = await client.list_tools()
        result = await client.call_tool("get_weather", {})

    assert listed.tools[0].output_schema == snapshot(
        {
            "properties": {
                "temperature": {"title": "Temperature", "type": "number"},
                "conditions": {"title": "Conditions", "type": "string"},
            },
            "required": ["temperature", "conditions"],
            "title": "Weather",
            "type": "object",
        }
    )
    assert result == snapshot(
        CallToolResult(
            content=[
                TextContent(
                    text="""\
{
  "temperature": 22.5,
  "conditions": "sunny"
}\
"""
                )
            ],
            structured_content={"temperature": 22.5, "conditions": "sunny"},
        )
    )


@requirement("mcpserver:tool:output-schema:wrapped")
async def test_call_tool_list_return_is_wrapped_in_result_key(connect: Connect) -> None:
    mcp = MCPServer("primes")

    @mcp.tool()
    def primes() -> list[int]:
        return [2, 3, 5]

    async with connect(mcp) as client:
        listed = await client.list_tools()
        result = await client.call_tool("primes", {})

    assert listed.tools[0].output_schema == snapshot(
        {
            "properties": {"result": {"items": {"type": "integer"}, "title": "Result", "type": "array"}},
            "required": ["result"],
            "title": "primesOutput",
            "type": "object",
        }
    )
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(text="2"), TextContent(text="3"), TextContent(text="5")],
            structured_content={"result": [2, 3, 5]},
        )
    )


@requirement("mcpserver:tool:input-validation")
async def test_call_tool_invalid_arguments_become_error_result(connect: Connect) -> None:
    mcp = MCPServer("adder")

    @mcp.tool()
    def add(a: int, b: int) -> str:
        """Validation rejects the arguments before the function is ever called."""
        raise NotImplementedError

    async with connect(mcp) as client:
        result = await client.call_tool("add", {"b": 3})

    # The message embeds version-specific raw pydantic output, so only the stable prefix is asserted.
    assert result.is_error is True
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text.startswith("Error executing tool add: 1 validation error")


@requirement("mcpserver:output-schema:server-validate")
@requirement("mcpserver:output-schema:missing-structured")
async def test_tool_with_output_schema_returning_mismatched_structured_content_is_an_error_result(
    connect: Connect,
) -> None:
    """`Annotated[CallToolResult, Model]` declares an output schema for a hand-built result.

    MCPServer validates the supplied structured_content (mismatched or missing) against that
    schema before returning.
    """
    mcp = MCPServer("forecaster")

    class Weather(BaseModel):
        temperature: float
        conditions: str

    @mcp.tool()
    def mismatched() -> Annotated[CallToolResult, Weather]:
        return CallToolResult(content=[TextContent(text="oops")], structured_content={"nope": True})

    @mcp.tool()
    def missing() -> Annotated[CallToolResult, Weather]:
        return CallToolResult(content=[TextContent(text="oops")])

    async with connect(mcp) as client:
        mismatched_result = await client.call_tool("mismatched", {})
        missing_result = await client.call_tool("missing", {})

    # Raw pydantic ValidationError text varies across pydantic versions, so only the stable prefix is asserted.
    assert mismatched_result.is_error is True
    assert isinstance(mismatched_result.content[0], TextContent)
    assert mismatched_result.content[0].text.startswith("Error executing tool mismatched: 2 validation errors")

    assert missing_result.is_error is True
    assert isinstance(missing_result.content[0], TextContent)
    assert missing_result.content[0].text.startswith("Error executing tool missing: 1 validation error")


@requirement("mcpserver:tool:duplicate-name")
async def test_registering_a_duplicate_tool_name_warns_and_keeps_the_first(connect: Connect) -> None:
    """The spec intends rejection at registration time; see the divergence note on the requirement."""
    mcp = MCPServer("duplicates")

    @mcp.tool()
    def echo() -> str:
        return "first"

    def echo_second() -> str:
        """Passed to add_tool with a duplicate name; the registration is discarded so this never runs."""
        raise NotImplementedError

    mcp.add_tool(echo_second, name="echo")

    async with connect(mcp) as client:
        listed = await client.list_tools()
        result = await client.call_tool("echo", {})

    assert [tool.name for tool in listed.tools] == ["echo"]
    assert result == snapshot(
        CallToolResult(content=[TextContent(text="first")], structured_content={"result": "first"})
    )


@requirement("mcpserver:tool:naming-validation")
async def test_registering_a_tool_with_a_spec_invalid_name_warns_but_does_not_reject(
    connect: Connect, caplog: pytest.LogCaptureFixture
) -> None:
    """SEP-986 intends rejection at registration; MCPServer warns and proceeds.

    See the divergence note on the requirement. The warning spans several SDK-authored records, so
    only the stable prefix and inclusion of the offending name are asserted.
    """
    mcp = MCPServer("naming")

    with caplog.at_level(logging.WARNING, logger="mcp.shared.tool_name_validation"):

        @mcp.tool(name="bad name!")
        def bad() -> str:
            return "ok"

    assert any(
        rec.levelno == logging.WARNING
        and rec.message.startswith("Tool name validation warning")
        and "bad name!" in rec.message
        for rec in caplog.records
    )

    async with connect(mcp) as client:
        listed = await client.list_tools()
        result = await client.call_tool("bad name!", {})

    assert [tool.name for tool in listed.tools] == ["bad name!"]
    assert result == snapshot(CallToolResult(content=[TextContent(text="ok")], structured_content={"result": "ok"}))


@requirement("mcpserver:tool:url-elicitation-error")
async def test_decorated_tool_raising_url_elicitation_required_surfaces_as_error_32042(connect: Connect) -> None:
    """Unlike other tool exceptions, this error is not wrapped as an is_error result.

    It is special-cased to propagate as the JSON-RPC error the client needs in order to present
    the listed URL interactions and retry the call.
    """
    mcp = MCPServer("authorizer")

    @mcp.tool()
    def read_files() -> str:
        raise UrlElicitationRequiredError(
            [
                ElicitRequestURLParams(
                    message="Authorization required for your files.",
                    url="https://example.com/oauth/authorize",
                    elicitation_id="auth-001",
                )
            ]
        )

    async with connect(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("read_files", {})

    assert exc_info.value.error.code == URL_ELICITATION_REQUIRED
    assert exc_info.value.error == snapshot(
        ErrorData(
            code=-32042,
            message="URL elicitation required",
            data={
                "elicitations": [
                    {
                        "mode": "url",
                        "message": "Authorization required for your files.",
                        "url": "https://example.com/oauth/authorize",
                        "elicitationId": "auth-001",
                    }
                ]
            },
        )
    )


@requirement("mcpserver:register:post-connect")
async def test_adding_and_removing_tools_does_not_notify_connected_clients(connect: Connect) -> None:
    """The spec provides notifications/tools/list_changed for this; MCPServer never sends it.

    The log notification is a sentinel proving notifications do reach the collector.
    """
    received: list[IncomingMessage] = []
    mcp = MCPServer("mutable")

    def extra() -> str:
        """A tool registered at runtime; never called."""
        raise NotImplementedError

    @mcp.tool()
    def doomed() -> str:
        """A tool removed at runtime; never called."""
        raise NotImplementedError

    @mcp.tool()
    async def grow(ctx: Context) -> str:
        mcp.add_tool(extra, name="extra")
        mcp.remove_tool("doomed")
        await ctx.info("tool set changed")  # pyright: ignore[reportDeprecated]
        return "mutated"

    async def collect(message: IncomingMessage) -> None:
        received.append(message)

    async with connect(mcp, message_handler=collect) as client:
        before = await client.list_tools()
        await client.call_tool("grow", {})
        after = await client.list_tools()

    assert [tool.name for tool in before.tools] == ["doomed", "grow"]
    assert [tool.name for tool in after.tools] == ["grow", "extra"]
    assert received == snapshot(
        [LoggingMessageNotification(params=LoggingMessageNotificationParams(level="info", data="tool set changed"))]
    )
