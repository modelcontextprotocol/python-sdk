"""Tool interactions against MCPServer, driven through the public Client API."""

from typing import Annotated

import pytest
from inline_snapshot import snapshot
from pydantic import BaseModel

from mcp import MCPError
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp.types import (
    URL_ELICITATION_REQUIRED,
    CallToolResult,
    ElicitRequestURLParams,
    ErrorData,
    LoggingMessageNotification,
    LoggingMessageNotificationParams,
    TextContent,
)
from tests.interaction._connect import Connect
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("tools:call:content:text")
async def test_call_tool_returns_text_content(connect: Connect) -> None:
    """Arguments reach the tool function; its return value comes back as text content.

    MCPServer also derives an output schema from the return annotation and attaches the
    matching structuredContent to the result.
    """
    mcp = MCPServer("adder")

    @mcp.tool()
    def add(a: int, b: int) -> str:
        return str(a + b)

    async with connect(mcp) as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})

    assert result == snapshot(CallToolResult(content=[TextContent(text="5")], structured_content={"result": "5"}))


@requirement("mcpserver:tool:handler-throws")
@requirement("mcpserver:output-schema:skip-on-error")
async def test_call_tool_function_exception_becomes_error_result(connect: Connect) -> None:
    """An exception raised by a tool function is returned as an is_error result, not a JSON-RPC error.

    The function's `-> str` annotation gives the tool a derived output schema, but the error
    result is built before any schema validation runs, so no validation failure is layered on
    top of the original exception.
    """
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
    """A ToolError raised by a tool function is returned as an is_error result, not a JSON-RPC error."""
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
    """Calling a tool name that was never registered is reported as an is_error result.

    The spec classifies unknown tools as a protocol error; see the divergence note on the
    requirement.
    """
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
    """A tool returning a pydantic model advertises the model's schema as the tool's output schema
    and returns the model's fields as structured content alongside a serialised text block.
    """
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
    """A tool returning a list wraps the value under a "result" key in both the generated output
    schema and the structured content.
    """
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
    """Arguments that fail validation against the tool's signature are reported as an is_error
    result describing the failure, not as a protocol error.
    """
    mcp = MCPServer("adder")

    @mcp.tool()
    def add(a: int, b: int) -> str:
        """Validation rejects the arguments before the function is ever called."""
        raise NotImplementedError

    async with connect(mcp) as client:
        result = await client.call_tool("add", {"b": 3})

    # The description is raw pydantic output -- it embeds a pydantic-version-specific
    # errors.pydantic.dev URL and the internal `addArguments` model name -- so only the stable
    # prefix is asserted; a full snapshot would break on every pydantic upgrade.
    assert result.is_error is True
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text.startswith("Error executing tool add: 1 validation error")


@requirement("mcpserver:output-schema:server-validate")
@requirement("mcpserver:output-schema:missing-structured")
async def test_tool_with_output_schema_returning_mismatched_structured_content_is_an_error_result(
    connect: Connect,
) -> None:
    """Structured content that fails the tool's own output schema is rejected on the server side.

    A tool annotated `Annotated[CallToolResult, Model]` returns a hand-built CallToolResult while
    declaring `Model` as its output schema; MCPServer validates the supplied structured_content
    against that schema before returning. The two cases -- a content shape that does not match,
    and no structured content at all -- both fail that validation and are reported as is_error
    results carrying the (raw pydantic) validation error wrapped in the SDK's stable prefix.
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

    # The body of each message is raw pydantic ValidationError output (model name, field paths,
    # an errors.pydantic.dev URL) and changes across pydantic versions, so only the SDK's stable
    # prefix is asserted.
    assert mismatched_result.is_error is True
    assert isinstance(mismatched_result.content[0], TextContent)
    assert mismatched_result.content[0].text.startswith("Error executing tool mismatched: 2 validation errors")

    assert missing_result.is_error is True
    assert isinstance(missing_result.content[0], TextContent)
    assert missing_result.content[0].text.startswith("Error executing tool missing: 1 validation error")


@requirement("mcpserver:tool:duplicate-name")
async def test_registering_a_duplicate_tool_name_warns_and_keeps_the_first(connect: Connect) -> None:
    """Registering a second tool with an already-used name keeps the first registration.

    The intended behaviour is rejection at registration time; MCPServer instead logs a warning
    and discards the second registration (see the divergence note on the requirement). The
    second function is registered via add_tool with an explicit name so the test does not
    redefine the same function name in this scope.
    """
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


@requirement("mcpserver:tool:url-elicitation-error")
async def test_decorated_tool_raising_url_elicitation_required_surfaces_as_error_32042(connect: Connect) -> None:
    """A decorated tool raising the URL-elicitation-required error reaches the client as error -32042.

    MCPServer wraps every other tool exception as an is_error result; this error is special-cased
    so it propagates as the JSON-RPC error the client needs in order to present the listed URL
    interactions and retry the call.
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
    """Mutating the tool set on a running server changes tools/list but sends no notification.

    add_tool and remove_tool only update the registry: a connected client that listed the tools
    before the mutation has no way to learn it should list them again. The spec provides
    notifications/tools/list_changed for exactly this; MCPServer never sends it. The tool emits
    one log message as a sentinel so the test proves notifications do reach the collector -- the
    log message arrives, a list_changed does not.
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
        await ctx.info("tool set changed")
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
