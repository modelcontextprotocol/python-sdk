import anyio

from mcp import Client
from mcp.types import TextContent


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        result = await client.call_tool("lookup_book", {"title": "Dune"})

        for block in result.content:
            if isinstance(block, TextContent):
                print(block.text)

        print(result.structured_content)
        print(result.is_error)


if __name__ == "__main__":
    anyio.run(main)
