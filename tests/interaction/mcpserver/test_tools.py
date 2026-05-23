"""Tool interactions against MCPServer, driven through the public Client API."""

import pytest
from inline_snapshot import snapshot

from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
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
