from mcp.server import MCPServer

mcp = MCPServer("Web")


@mcp.tool()
def search(query: str) -> str:
    """Search the web."""
    return f"12 pages match {query!r}."
