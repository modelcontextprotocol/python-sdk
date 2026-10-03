from typing import Literal

import anyio

import mcp.types as types
from mcp import Client
from mcp.client import advertise

EXTENSION_ID = "com.example/search"


class SearchParams(types.RequestParams):
    query: str
    limit: int = 10


class SearchResult(types.Result):
    items: list[str]


class SearchRequest(types.Request[SearchParams, Literal["com.example/search"]]):
    method: Literal["com.example/search"] = "com.example/search"
    params: SearchParams


async def main() -> None:
    async with Client("http://localhost:8000/mcp", extensions=[advertise(EXTENSION_ID)]) as client:
        request = SearchRequest(params=SearchParams(query="mcp", limit=3))
        result = await client.session.send_request(request, SearchResult)
        print(result.items)
        # ['mcp-0', 'mcp-1', 'mcp-2']


if __name__ == "__main__":
    anyio.run(main)
