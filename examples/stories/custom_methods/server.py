"""Register a vendor-prefixed JSON-RPC method on the low-level Server.

`MCPServer` has no public surface for arbitrary method registration, so this
story's `server.py` is lowlevel-native (no `server_lowlevel.py` sibling).
"""

from typing import Any

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import run_server_from_args


class SearchParams(types.RequestParams):
    """Subclass `RequestParams` so `_meta` (and the 2026 envelope keys) parse uniformly."""

    query: str
    limit: int = 10


class SearchResult(types.Result):
    items: list[str]


def build_server() -> Server[Any]:
    server = Server("acme-search")

    async def search(ctx: ServerRequestContext[Any], params: SearchParams) -> SearchResult:
        items = [f"{params.query}-{i}" for i in range(params.limit)]
        return SearchResult(items=items)

    server.add_request_handler("acme/search", SearchParams, search)
    return server


if __name__ == "__main__":
    run_server_from_args(build_server)
