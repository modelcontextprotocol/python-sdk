import pytest

from mcp.server.mcpserver import MCPServer

pytestmark = pytest.mark.anyio


async def test_list_tools_returns_all_tools():
    mcp = MCPServer("TestTools")

    num_tools = 100
    for i in range(num_tools):

        @mcp.tool(name=f"tool_{i}")
        def dummy_tool_func():  # pragma: no cover
            f"""Tool number {i}"""
            return i

        globals()[f"dummy_tool_{i}"] = dummy_tool_func  # Keep reference to avoid garbage collection

    tools = await mcp.list_tools()

    assert len(tools) == num_tools, f"Expected {num_tools} tools, but got {len(tools)}"

    tool_names = [tool.name for tool in tools]
    expected_names = [f"tool_{i}" for i in range(num_tools)]
    assert sorted(tool_names) == sorted(expected_names), "Tool names don't match expected names"
