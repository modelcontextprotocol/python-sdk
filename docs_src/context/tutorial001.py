from mcp.server import MCPServer
from mcp.server.mcpserver import Context

mcp = MCPServer("Bookshop")


@mcp.tool()
def search_books(query: str, ctx: Context) -> str:
    """Search the catalog by title or author."""
    return f"[request {ctx.request_id}] Found 3 books matching {query!r}."
