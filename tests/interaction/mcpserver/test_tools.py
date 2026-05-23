"""Tool interactions against MCPServer, driven through the public Client API."""

import pytest
from inline_snapshot import snapshot
from pydantic import BaseModel

from mcp.client.client import Client
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import (
    CallToolResult,
    LoggingMessageNotification,
    LoggingMessageNotificationParams,
    TextContent,
)
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("tools:call:content:text")
async def test_call_tool_returns_text_content() -> None:
    """Arguments reach the tool function; its return value comes back as text content.

    MCPServer also derives an output schema from the return annotation and attaches the
    matching structuredContent to the result.
    """
    mcp = MCPServer("adder")

    @mcp.tool()
    def add(a: int, b: int) -> str:
        return str(a + b)

    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})

    assert result == snapshot(CallToolResult(content=[TextContent(text="5")], structured_content={"result": "5"}))


@requirement("mcpserver:tools:handler-exception")
async def test_call_tool_function_exception_becomes_error_result() -> None:
    """An exception raised by a tool function is returned as an is_error result, not a JSON-RPC error."""
    mcp = MCPServer("errors")

    @mcp.tool()
    def explode() -> str:
        raise ValueError("boom")

    async with Client(mcp) as client:
        result = await client.call_tool("explode", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="Error executing tool explode: boom")], is_error=True)
    )


@requirement("mcpserver:tools:handler-exception")
async def test_call_tool_tool_error_becomes_error_result() -> None:
    """A ToolError raised by a tool function is returned as an is_error result, not a JSON-RPC error."""
    mcp = MCPServer("errors")

    @mcp.tool()
    def flux() -> str:
        raise ToolError("flux capacitor offline")

    async with Client(mcp) as client:
        result = await client.call_tool("flux", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="Error executing tool flux: flux capacitor offline")], is_error=True)
    )


@requirement("mcpserver:tools:unknown-name")
async def test_call_tool_unknown_name_returns_error_result() -> None:
    """Calling a tool name that was never registered is reported as an is_error result.

    The spec classifies unknown tools as a protocol error; see the divergence note on the
    requirement.
    """
    mcp = MCPServer("errors")

    @mcp.tool()
    def add() -> None:
        """A registered tool; the test calls a different name."""

    async with Client(mcp) as client:
        result = await client.call_tool("nope", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="Unknown tool: nope")], is_error=True))


@requirement("mcpserver:tools:output-schema:model")
async def test_call_tool_model_return_becomes_structured_content() -> None:
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

    async with Client(mcp) as client:
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


@requirement("mcpserver:tools:output-schema:wrapped")
async def test_call_tool_list_return_is_wrapped_in_result_key() -> None:
    """A tool returning a list wraps the value under a "result" key in both the generated output
    schema and the structured content.
    """
    mcp = MCPServer("primes")

    @mcp.tool()
    def primes() -> list[int]:
        return [2, 3, 5]

    async with Client(mcp) as client:
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


@requirement("tools:call:invalid-arguments")
async def test_call_tool_invalid_arguments_become_error_result() -> None:
    """Arguments that fail validation against the tool's signature are reported as an is_error
    result describing the failure, not as a protocol error.

    The description is raw pydantic output (version-dependent and leaking the internal argument
    model name), so only the stable prefix is asserted rather than the full text.
    """
    mcp = MCPServer("adder")

    @mcp.tool()
    def add(a: int, b: int) -> str:
        """Validation rejects the arguments before the function is ever called."""
        raise NotImplementedError

    async with Client(mcp) as client:
        result = await client.call_tool("add", {"b": 3})

    assert result.is_error is True
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text.startswith("Error executing tool add: 1 validation error")


@requirement("mcpserver:tools:list-changed-on-mutation")
async def test_adding_and_removing_tools_does_not_notify_connected_clients() -> None:
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

    async with Client(mcp, message_handler=collect) as client:
        before = await client.list_tools()
        await client.call_tool("grow", {})
        after = await client.list_tools()

    assert [tool.name for tool in before.tools] == ["doomed", "grow"]
    assert [tool.name for tool in after.tools] == ["grow", "extra"]
    assert received == snapshot(
        [LoggingMessageNotification(params=LoggingMessageNotificationParams(level="info", data="tool set changed"))]
    )
