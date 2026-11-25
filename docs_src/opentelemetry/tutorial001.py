from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


@mcp.tool()
def search_books(query: str) -> str:
    """Search the catalog by title or author."""
    return f"Found 3 books matching {query!r}."
