"""MCPServer Echo Server"""

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("Echo Server")


@mcp.tool()
def echo(text: str) -> str:
    """Echo the input text"""
    return text
