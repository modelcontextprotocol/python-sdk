"""Test that parameter descriptions are properly exposed through list_tools"""

import pytest
from pydantic import Field

from mcp.server.fastmcp import FastMCP


@pytest.mark.anyio
async def test_parameter_descriptions():
    mcp = FastMCP("Test Server")

    @mcp.tool()
    def greet(
        name: str = Field(description="The name to greet"),
        title: str = Field(description="Optional title", default=""),
    ) -> str:
        """A greeting tool"""
        return f"Hello {title} {name}"

    tools = await mcp.list_tools()
    assert len(tools) == 1
    tool = tools[0]

    # Check that parameter descriptions are present in the schema
    properties = tool.inputSchema["properties"]
    assert "name" in properties
    assert properties["name"]["description"] == "The name to greet"
    assert "title" in properties
    assert properties["title"]["description"] == "Optional title"
