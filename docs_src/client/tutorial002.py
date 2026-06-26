from mcp import Client
from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


@mcp.tool(title="Search the catalog")
def search_books(query: str, limit: int = 10) -> str:
    """Search the catalog by title or author."""
    return f"Found 3 books matching {query!r} (showing up to {limit})."


async def main() -> None:
    async with Client(mcp) as client:
        result = await client.list_tools()
        for tool in result.tools:
            print(tool.name)
            print(tool.title)
            print(tool.description)
            print(tool.input_schema)
