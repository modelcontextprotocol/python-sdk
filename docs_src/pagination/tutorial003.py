from typing import Any

from mcp_types import ListResourcesResult, PaginatedRequestParams, Resource

from mcp import Client
from mcp.server import Server, ServerRequestContext

BOOKS = [f"book-{n}" for n in range(1, 101)]

PAGE_SIZE = 10


async def list_books(ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None) -> ListResourcesResult:
    start = 0 if params is None or params.cursor is None else int(params.cursor)
    end = start + PAGE_SIZE
    page = [Resource(uri=f"books://catalog/{name}", name=name) for name in BOOKS[start:end]]
    next_cursor = str(end) if end < len(BOOKS) else None
    return ListResourcesResult(resources=page, next_cursor=next_cursor)


server = Server("Bookshop", on_list_resources=list_books)


async def main() -> None:
    async with Client(server) as client:
        # Every page, stitched into one list.
        resources = await client.list_all_resources()
        print(f"{len(resources)} resources")

        # Or stream them, and stop as soon as you have what you need.
        async for resource in client.iter_all_resources():
            print(f"first: {resource.name}")
            break
