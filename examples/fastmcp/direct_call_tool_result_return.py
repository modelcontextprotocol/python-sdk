"""
FastMCP Echo Server with direct CallToolResult return
"""

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

mcp = FastMCP("Echo Server")


@mcp.tool()
def echo(text: str) -> CallToolResult:
    """Echo the input text with structure and metadata"""
    return CallToolResult(
        content=[TextContent(type="text", text=text)], structuredContent={"text": text}, _meta={"some": "metadata"}
    )
