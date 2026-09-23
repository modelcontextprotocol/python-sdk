from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


@mcp.tool()
def search_books(query: str) -> str:
    """Search the catalog by title or author."""
    return f"Found 3 books matching {query!r}."


@mcp.resource("catalog://featured")
def featured_books() -> str:
    """The featured books shelf."""
    return "Dune\nThe Left Hand of Darkness\nA Wizard of Earthsea"


@mcp.prompt()
def reading_prompt(topic: str) -> str:
    """Create a reading recommendation prompt."""
    return f"Recommend one book about {topic}."
