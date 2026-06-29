"""Example showing direct CallToolResult return for advanced control."""

from typing import Annotated

from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("CallToolResult Example")


class ValidationModel(BaseModel):
    status: str
    data: dict[str, int]


@mcp.tool()
def advanced_tool() -> CallToolResult:
    """Return CallToolResult directly for full control including _meta field."""
    return CallToolResult(
        content=[TextContent(type="text", text="Response visible to the model")],
        _meta={"hidden": "data for client applications only"},
    )


@mcp.tool()
def validated_tool() -> Annotated[CallToolResult, ValidationModel]:
    """Return CallToolResult with structured output validation."""
    return CallToolResult(
        content=[TextContent(type="text", text="Validated response")],
        structured_content={"status": "success", "data": {"result": 42}},
        _meta={"internal": "metadata"},
    )


@mcp.tool()
def empty_result_tool() -> CallToolResult:
    """For empty results, return CallToolResult with empty content."""
    return CallToolResult(content=[])
