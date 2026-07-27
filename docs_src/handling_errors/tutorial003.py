from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError

mcp = MCPServer("Bookshop")

CATALOG = {"Dune": "Frank Herbert", "Neuromancer": "William Gibson"}


@mcp.resource("books://{title}")
def book(title: str) -> str:
    """The catalog entry for one book."""
    if title not in CATALOG:
        raise ResourceNotFoundError(f"No book titled {title!r} in the catalog.")
    return f"{title} by {CATALOG[title]}"
