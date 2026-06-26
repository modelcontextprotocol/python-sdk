from typing import Annotated, Literal

from pydantic import Field

from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


@mcp.tool()
def search_books(
    query: Annotated[str, Field(description="Title or author to search for.")],
    limit: Annotated[int, Field(ge=1, le=50, description="Maximum number of results.")] = 10,
    genre: Literal["fiction", "non-fiction", "poetry"] | None = None,
) -> str:
    """Search the catalog by title or author."""
    where = f" in {genre}" if genre else ""
    return f"Found 3 books matching {query!r}{where} (showing up to {limit})."
