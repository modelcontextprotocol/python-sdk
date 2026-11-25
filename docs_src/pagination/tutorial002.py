import anyio

from mcp import Client
from mcp.types import Resource


async def list_all_resources(client: Client) -> list[Resource]:
    resources: list[Resource] = []
    cursor: str | None = None
    while True:
        page = await client.list_resources(cursor=cursor)
        resources.extend(page.resources)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    return resources


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        resources = await list_all_resources(client)
        print(f"{len(resources)} resources")


if __name__ == "__main__":
    anyio.run(main)
