import anyio

from mcp import Client
from mcp.types import Tool


async def list_all_tools(client: Client) -> list[Tool]:
    tools: list[Tool] = []
    cursor: str | None = None
    while True:
        page = await client.list_tools(cursor=cursor)
        tools.extend(page.tools)
        if page.next_cursor is None:
            return tools
        cursor = page.next_cursor


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        tools = await list_all_tools(client)
        print([tool.name for tool in tools])


if __name__ == "__main__":
    anyio.run(main)
