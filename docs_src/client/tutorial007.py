from mcp_types import Tool

from mcp import Client
from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


@mcp.tool()
def search_books(query: str) -> str:
    """Search the catalog by title or author."""
    return f"Found 3 books matching {query!r}."


@mcp.tool()
def reserve_book(title: str) -> str:
    """Put a book on hold."""
    return f"Reserved {title!r}."


async def main() -> None:
    async with Client(mcp) as client:
        tools: list[Tool] = []
        cursor: str | None = None
        while True:
            page = await client.list_tools(cursor=cursor)
            tools.extend(page.tools)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        print([tool.name for tool in tools])
