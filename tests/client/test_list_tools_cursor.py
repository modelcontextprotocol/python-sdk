import pytest

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import (
    create_connected_server_and_client_session as create_session,
)

# Mark the whole module for async tests
pytestmark = pytest.mark.anyio


async def test_list_tools_with_cursor_pagination():
    """Test list_tools with cursor pagination using a server with many tools."""
    server = FastMCP("test")

    # Create 100 tools to test pagination
    num_tools = 100
    for i in range(num_tools):

        @server.tool(name=f"tool_{i}")
        async def dummy_tool(index: int = i) -> str:
            f"""Tool number {index}"""
            return f"Result from tool {index}"

        # Keep reference to avoid garbage collection
        globals()[f"dummy_tool_{i}"] = dummy_tool

    async with create_session(server._mcp_server) as client_session:
        all_tools = []
        cursor = None

        # Paginate through all results
        while True:
            result = await client_session.list_tools(cursor=cursor)
            all_tools.extend(result.tools)

            if result.nextCursor is None:
                break

            cursor = result.nextCursor

        # Verify we got all tools
        assert len(all_tools) == num_tools

        # Verify each tool is unique and has the correct name
        tool_names = [tool.name for tool in all_tools]
        expected_names = [f"tool_{i}" for i in range(num_tools)]
        assert sorted(tool_names) == sorted(expected_names)


async def test_list_tools_without_cursor():
    """Test the list_tools method without cursor (backward compatibility)."""
    server = FastMCP("test")

    # Create a few tools
    @server.tool(name="test_tool_1")
    async def test_tool_1() -> str:
        """First test tool"""
        return "Result 1"

    @server.tool(name="test_tool_2")
    async def test_tool_2() -> str:
        """Second test tool"""
        return "Result 2"

    async with create_session(server._mcp_server) as client_session:
        # Should work without cursor argument
        result = await client_session.list_tools()
        assert len(result.tools) == 2
        tool_names = [tool.name for tool in result.tools]
        assert "test_tool_1" in tool_names
        assert "test_tool_2" in tool_names


async def test_list_tools_cursor_parameter_accepted():
    """Test that the cursor parameter is accepted by the client method."""
    server = FastMCP("test")

    # Create a few tools
    for i in range(5):

        @server.tool(name=f"tool_{i}")
        async def dummy_tool(index: int = i) -> str:
            f"""Tool number {index}"""
            return f"Result from tool {index}"

        globals()[f"dummy_tool_{i}"] = dummy_tool

    async with create_session(server._mcp_server) as client_session:
        # Test that cursor parameter is accepted
        result1 = await client_session.list_tools()
        assert len(result1.tools) == 5

        # Test with explicit None cursor
        result2 = await client_session.list_tools(cursor=None)
        assert len(result2.tools) == 5

        # Test with a cursor value (even though this server doesn't paginate)
        result3 = await client_session.list_tools(cursor="some_cursor")
        # The cursor is sent to the server, but this particular server ignores it
        assert len(result3.tools) == 5
