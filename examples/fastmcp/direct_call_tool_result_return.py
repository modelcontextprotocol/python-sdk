"""
FastMCP Echo Server with direct CallToolResult return
"""

from typing import Annotated

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

mcp = FastMCP("Echo Server")


class EchoResponse(BaseModel):
    text: str


@mcp.tool()
def echo(text: str) -> Annotated[CallToolResult, EchoResponse]:
    """Echo the input text with structure and metadata"""
    return CallToolResult(
        content=[TextContent(type="text", text=text)], structuredContent={"text": text}, _meta={"some": "metadata"}
    )
