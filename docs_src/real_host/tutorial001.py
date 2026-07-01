from mcp.server import MCPServer

mcp = MCPServer("Bookshop")

CATALOG = {
    "Dune": "Frank Herbert",
    "Neuromancer": "William Gibson",
    "The Left Hand of Darkness": "Ursula K. Le Guin",
}


@mcp.tool()
def search_books(query: str) -> list[str]:
    """Search the catalog by title or author."""
    needle = query.lower()
    return [title for title, author in CATALOG.items() if needle in title.lower() or needle in author.lower()]


@mcp.tool()
def get_author(title: str) -> str:
    """Look up the author of a book in the catalog."""
    if title not in CATALOG:
        raise ValueError(f"No book titled {title!r} in the catalog.")
    return CATALOG[title]


@mcp.resource("catalog://titles")
def titles() -> str:
    """Every title in the catalog, one per line."""
    return "\n".join(sorted(CATALOG))


if __name__ == "__main__":
    mcp.run()
