from mcp.server import MCPServer

mcp = MCPServer("Bookshop", log_level="DEBUG")


@mcp.tool()
def search_books(query: str) -> str:
    """Search the catalog by title or author."""
    return f"Found 3 books matching {query!r}."


if __name__ == "__main__":
    mcp.run()
