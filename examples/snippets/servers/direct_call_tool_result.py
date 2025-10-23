"""Example showing direct CallToolResult return for advanced control."""

from typing import Annotated

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

mcp = FastMCP("CallToolResult Example")


class ValidationModel(BaseModel):
    """Model for validating structured output."""

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
        structuredContent={"status": "success", "data": {"result": 42}},
        _meta={"internal": "metadata"},
    )


@mcp.tool()
def empty_result_tool() -> CallToolResult:
    """For empty results, return CallToolResult with empty content."""
    return CallToolResult(content=[])
