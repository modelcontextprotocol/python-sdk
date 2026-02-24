"""Regression test for issue #592.

When a tool returns a CallToolResult (directly or nested in a list), the client
should receive the TextContent.text value as-is, not as the JSON serialization
of the entire CallToolResult object.
"""

import pytest

from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

pytestmark = pytest.mark.anyio


@pytest.fixture
def app() -> MCPServer:
    server = MCPServer("test")

    @server.tool("echo_direct")
    async def echo_direct(message: int = 0) -> CallToolResult:
        """Return CallToolResult directly with a primitive text value."""
        return CallToolResult(content=[TextContent(type="text", text=str(message))])

    @server.tool("echo_in_list")
    async def echo_in_list(message: int = 0):  # type: ignore[return]
        """Return CallToolResult nested inside a list."""
        return [CallToolResult(content=[TextContent(type="text", text=str(message))])]

    return server


async def test_call_tool_result_direct_returns_primitive_text(app: MCPServer) -> None:
    """A tool returning CallToolResult directly should preserve TextContent.text."""
    async with Client(app) as client:
        result = await client.call_tool("echo_direct", {"message": 42})
        assert len(result.content) == 1
        text_content = result.content[0]
        assert isinstance(text_content, TextContent)
        assert text_content.text == "42"


async def test_call_tool_result_in_list_returns_primitive_text(app: MCPServer) -> None:
    """A tool returning [CallToolResult(...)] should preserve TextContent.text, not
    serialize the entire CallToolResult object as JSON into the text field."""
    async with Client(app) as client:
        result = await client.call_tool("echo_in_list", {"message": 42})
        assert len(result.content) == 1
        text_content = result.content[0]
        assert isinstance(text_content, TextContent)
        # Before the fix, this would be the full JSON of the CallToolResult object
        assert text_content.text == "42"
