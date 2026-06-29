"""Paginated resources/list (lowlevel API): pages of two via an opaque integer-offset cursor."""

from typing import Any

import mcp_types as types

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import MCPError
from stories._hosting import run_server_from_args

WORDS = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")
PAGE_SIZE = 2


def build_server() -> Server[Any]:
    async def list_resources(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        start = 0
        if params is not None and params.cursor is not None:
            if not params.cursor.isdigit() or int(params.cursor) >= len(WORDS):
                raise MCPError(code=types.INVALID_PARAMS, message=f"Unknown cursor: {params.cursor!r}")
            start = int(params.cursor)
        page = WORDS[start : start + PAGE_SIZE]
        next_start = start + PAGE_SIZE
        return types.ListResourcesResult(
            resources=[types.Resource(uri=f"word://{w}", name=w) for w in page],
            next_cursor=str(next_start) if next_start < len(WORDS) else None,
        )

    return Server("pagination-example", on_list_resources=list_resources)


if __name__ == "__main__":
    run_server_from_args(build_server)
