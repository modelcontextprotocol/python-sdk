from mcp_types import TextContent
from pydantic import BaseModel

from mcp import Client
from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


class Book(BaseModel):
    title: str
    author: str
    year: int


@mcp.tool()
def lookup_book(title: str) -> Book:
    """Look up a book by its exact title."""
    if title != "Dune":
        raise ValueError(f"No book titled {title!r} in the catalog.")
    return Book(title="Dune", author="Frank Herbert", year=1965)


async def main() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("lookup_book", {"title": "Dune"})

        for block in result.content:
            if isinstance(block, TextContent):
                print(block.text)

        print(result.structured_content)
        print(result.is_error)
