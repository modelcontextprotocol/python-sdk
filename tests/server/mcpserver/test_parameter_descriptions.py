import pytest
from pydantic import Field

from mcp.server.mcpserver import MCPServer


@pytest.mark.anyio
async def test_parameter_descriptions():
    mcp = MCPServer("Test Server")

    @mcp.tool()
    def greet(
        name: str = Field(description="The name to greet"),
        title: str = Field(description="Optional title", default=""),
    ) -> str:  # pragma: no cover
        """A greeting tool"""
        return f"Hello {title} {name}"

    tools = await mcp.list_tools()
    assert len(tools) == 1
    tool = tools[0]

    properties = tool.input_schema["properties"]
    assert "name" in properties
    assert properties["name"]["description"] == "The name to greet"
    assert "title" in properties
    assert properties["title"]["description"] == "Optional title"
