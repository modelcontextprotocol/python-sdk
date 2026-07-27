from mcp import Client
from mcp.server import MCPServer

mcp = MCPServer("Bookshop", instructions="Search the catalog before recommending a book.")


@mcp.tool()
def search_books(query: str) -> str:
    """Search the catalog by title or author."""
    return f"Found 3 books matching {query!r}."


async def main() -> None:
    async with Client(mcp) as client:
        print(client.server_info)
        print(client.server_capabilities)
        print(client.protocol_version)
        print(client.instructions)
