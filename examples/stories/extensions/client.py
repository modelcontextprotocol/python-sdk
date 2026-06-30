"""Discover an extension's capability entry, call its tool, then send its vendor method."""

from typing import Literal

import mcp_types as types
from mcp_types import TextContent

from mcp.client import Client, advertise
from stories._harness import Target, run_client

EXTENSION_ID = "com.example/catalog"


class SearchParams(types.RequestParams):
    query: str
    limit: int = 3


class SearchRequest(types.Request[SearchParams, Literal["com.example/search"]]):
    method: Literal["com.example/search"] = "com.example/search"
    params: SearchParams


class SearchResult(types.Result):
    items: list[str]


async def main(target: Target, *, mode: str = "auto") -> None:
    # Declare the extension client-side so the server's `require_client_extension`
    # gate on `com.example/search` passes.
    async with Client(target, mode=mode, extensions=[advertise(EXTENSION_ID)]) as client:
        # The extensions capability map rides `server/discover` (modern only). On a
        # legacy connection it is absent, so assert it only when present.
        if client.server_capabilities.extensions is not None:
            assert client.server_capabilities.extensions == {EXTENSION_ID: {"suggest": True}}, (
                client.server_capabilities.extensions
            )

        # The extension's tool is a regular tool: listed and callable like any other.
        listed = await client.list_tools()
        assert [tool.name for tool in listed.tools] == ["suggest"], listed
        result = await client.call_tool("suggest", {"prefix": "mcp"})
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "mcp-suggestion", result.content[0].text

        # Vendor methods drop one layer to `client.session` (see custom_methods/).
        request = SearchRequest(params=SearchParams(query="mcp", limit=3))
        found = await client.session.send_request(request, SearchResult)
        assert found.items == ["mcp-0", "mcp-1", "mcp-2"], found


if __name__ == "__main__":
    run_client(main)
