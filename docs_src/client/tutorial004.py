from mcp_types import TextResourceContents

from mcp import Client
from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


@mcp.resource("catalog://genres")
def genres() -> list[str]:
    """The genres the catalog is organised by."""
    return ["fiction", "non-fiction", "poetry"]


@mcp.resource("catalog://genres/{genre}")
def books_in_genre(genre: str) -> str:
    """Every title we stock in one genre."""
    return f"3 books filed under {genre}."


async def main() -> None:
    async with Client(mcp) as client:
        listed = await client.list_resources()
        print([resource.uri for resource in listed.resources])

        templates = await client.list_resource_templates()
        print([template.uri_template for template in templates.resource_templates])

        result = await client.read_resource("catalog://genres/poetry")
        for contents in result.contents:
            if isinstance(contents, TextResourceContents):
                print(contents.text)
