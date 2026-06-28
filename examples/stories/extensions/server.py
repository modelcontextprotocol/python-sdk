"""Package a vendor verb and a tool as a reusable, advertised extension (SEP-2133).

`custom_methods/` registers a verb on the lowlevel `Server` by hand; this story
bundles the same idea as an `Extension`: declared contributions, a settings entry
under `ServerCapabilities.extensions`, and a `require_client_extension` gate on
the vendor method.
"""

from collections.abc import Sequence
from typing import Any

import mcp_types as types

from mcp.server.context import ServerRequestContext
from mcp.server.extension import Extension, MethodBinding, ToolBinding
from mcp.server.mcpserver import MCPServer, require_client_extension
from stories._hosting import run_server_from_args

EXTENSION_ID = "com.example/catalog"


class SearchParams(types.RequestParams):
    """Subclass `RequestParams` so `_meta` (and the 2026 envelope keys) parse uniformly."""

    query: str
    limit: int = 3


class SearchResult(types.Result):
    items: list[str]


def suggest(prefix: str) -> str:
    """Suggest a catalog entry for a prefix."""
    return f"{prefix}-suggestion"


async def search(ctx: ServerRequestContext[Any, Any], params: SearchParams) -> SearchResult:
    require_client_extension(ctx, EXTENSION_ID)
    return SearchResult(items=[f"{params.query}-{n}" for n in range(params.limit)])


class Catalog(Extension):
    """One identifier, three contributions: settings, a tool, a vendor method."""

    identifier = EXTENSION_ID

    def settings(self) -> dict[str, Any]:
        return {"suggest": True}

    def tools(self) -> Sequence[ToolBinding]:
        return [ToolBinding(fn=suggest)]

    def methods(self) -> Sequence[MethodBinding]:
        return [MethodBinding("com.example/search", SearchParams, search)]


def build_server() -> MCPServer:
    return MCPServer("extensions-example", extensions=[Catalog()])


if __name__ == "__main__":
    run_server_from_args(build_server)
