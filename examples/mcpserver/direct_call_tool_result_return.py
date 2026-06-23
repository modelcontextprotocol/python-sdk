# TODO: superseded by examples/stories/tools/; remove once tests/test_examples.py is migrated.
"""MCPServer Echo Server with direct CallToolResult return"""

from typing import Annotated

from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("Echo Server")


class EchoResponse(BaseModel):
    text: str


@mcp.tool()
def echo(text: str) -> Annotated[CallToolResult, EchoResponse]:
    """Echo the input text with structure and metadata"""
    return CallToolResult(
        content=[TextContent(type="text", text=text)], structured_content={"text": text}, _meta={"some": "metadata"}
    )
