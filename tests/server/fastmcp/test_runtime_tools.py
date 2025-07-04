"""Integration tests for runtime tools functionality."""

import pytest

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools.base import Tool
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent


@pytest.mark.anyio
async def test_runtime_tools():
    """Test that runtime tools work correctly."""

    async def runtime_mcp_tools_generator() -> list[Tool]:
        """Generate runtime tools."""

        def runtime_tool_1(message: str):
            return message

        def runtime_tool_2(message: str):
            return message

        return [Tool.from_function(runtime_tool_1), Tool.from_function(runtime_tool_2)]

    # Create server with various tool configurations, both static and runtime
    mcp = FastMCP(name="RuntimeToolsTestServer", runtime_mcp_tools_generator=runtime_mcp_tools_generator)

    # Static tool
    @mcp.tool(description="Static tool")
    def static_tool(message: str) -> str:
        return message

    # Start server and connect client
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        await client.initialize()

        # List tools
        tools_result = await client.list_tools()
        tool_names = {tool.name: tool for tool in tools_result.tools}

        # Verify both tools
        assert "static_tool" in tool_names
        assert "runtime_tool_1" in tool_names
        assert "runtime_tool_2" in tool_names

        # Check static tool
        result = await client.call_tool("static_tool", {"message": "This is a test"})
        assert len(result.content) == 1
        content = result.content[0]
        assert isinstance(content, TextContent)
        assert content.text == "This is a test"

        # Check runtime tool 1
        result = await client.call_tool("runtime_tool_1", {"message": "This is a test"})
        assert len(result.content) == 1
        content = result.content[0]
        assert isinstance(content, TextContent)
        assert content.text == "This is a test"

        # Check runtime tool 2
        result = await client.call_tool("runtime_tool_2", {"message": "This is a test"})
        assert len(result.content) == 1
        content = result.content[0]
        assert isinstance(content, TextContent)
        assert content.text == "This is a test"

        # Check non existing tool
        result = await client.call_tool("non_existing_tool", {"message": "This is a test"})
        assert len(result.content) == 1
        content = result.content[0]
        assert isinstance(content, TextContent)
        assert content.text == "Unknown tool: non_existing_tool"
