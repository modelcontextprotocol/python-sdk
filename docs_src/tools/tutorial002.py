from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


@mcp.tool()
def search_books(query: str, limit: int = 10) -> str:
    """Search the catalog by title or author."""
    return f"Found 3 books matching {query!r} (showing up to {limit})."
