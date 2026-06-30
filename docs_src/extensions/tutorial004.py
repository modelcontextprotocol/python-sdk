from collections.abc import Sequence
from typing import Any, Literal

import mcp_types as types
from pydantic import Field

from mcp import Client
from mcp.server.context import ServerRequestContext
from mcp.server.extension import Extension, MethodBinding
from mcp.server.mcpserver import MCPServer, require_client_extension

EXTENSION_ID = "com.example/search"


class SearchParams(types.RequestParams):
    query: str
    limit: int = Field(default=10, ge=1, le=100)


class SearchResult(types.Result):
    items: list[str]


class SearchRequest(types.Request[SearchParams, Literal["com.example/search"]]):
    method: Literal["com.example/search"] = "com.example/search"
    params: SearchParams


async def search(ctx: ServerRequestContext[Any, Any], params: SearchParams) -> SearchResult:
    require_client_extension(ctx, EXTENSION_ID)
    return SearchResult(items=[f"{params.query}-{n}" for n in range(params.limit)])


class Search(Extension):
    """An extension that serves its own request method."""

    identifier = EXTENSION_ID

    def methods(self) -> Sequence[MethodBinding]:
        return [
            MethodBinding(
                "com.example/search",
                SearchParams,
                search,
                protocol_versions=frozenset({"2026-07-28"}),
            )
        ]


mcp = MCPServer("catalog", extensions=[Search()])


async def main() -> None:
    async with Client(mcp, extensions={EXTENSION_ID: {}}) as client:
        request = SearchRequest(params=SearchParams(query="mcp", limit=3))
        result = await client.session.send_request(request, SearchResult)
        print(result.items)
        # ['mcp-0', 'mcp-1', 'mcp-2']
