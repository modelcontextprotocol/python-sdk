import base64

from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


@mcp.resource("docs://readme", mime_type="text/markdown")
def readme() -> str:
    """How to use this server."""
    return "# Bookshop\n\nSearch the catalog with the `search_books` tool."


@mcp.resource("stats://catalog", mime_type="application/json")
def catalog_stats() -> dict[str, int]:
    """Live counts for the catalog."""
    return {"books": 1204, "authors": 391}


@mcp.resource("covers://placeholder", mime_type="image/gif")
def placeholder_cover() -> bytes:
    """A 1x1 transparent GIF, shown when a book has no cover."""
    return base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
