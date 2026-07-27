from mcp import Client
from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


@mcp.tool()
def search_books(query: str) -> str:
    """Search the catalog by title or author."""
    return f"Found 3 books matching {query!r}."


async def main() -> None:
    async with Client(mcp, mode="legacy") as client:
        print(client.protocol_version)
