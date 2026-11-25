from mcp.server import MCPServer

mcp = MCPServer("Library")


@mcp.tool()
def search(query: str) -> str:
    """Search the library catalog."""
    return f"3 books match {query!r}."


@mcp.resource("library://hours")
def hours() -> str:
    """When the library is open."""
    return "Mon-Fri 09:00-17:00"
