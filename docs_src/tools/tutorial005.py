from mcp_types import ToolAnnotations

from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


@mcp.tool(
    title="Search the catalog",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
def search_books(query: str) -> str:
    """Search the catalog by title or author."""
    return f"Found 3 books matching {query!r}."
