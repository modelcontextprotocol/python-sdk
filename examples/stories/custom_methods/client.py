"""Send a vendor-prefixed request via the `client.session` escape hatch."""

from typing import Literal, cast

import mcp_types as types

from mcp.client import Client
from stories._harness import Target, run_client


class SearchParams(types.RequestParams):
    query: str
    limit: int = 10


class SearchRequest(types.Request[SearchParams, Literal["acme/search"]]):
    method: Literal["acme/search"] = "acme/search"
    params: SearchParams


class SearchResult(types.Result):
    items: list[str]


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
        # `Client` only exposes spec-defined verbs, so vendor methods have to drop one
        # layer to `client.session` today — there is no `Client`-level API for them
        # yet, and whether `.session` stays public is undecided. `send_request` is
        # typed against the closed `ClientRequest` union, hence the cast; at runtime
        # the body only calls `.model_dump()` and the unknown method skips the
        # per-spec result-validation registry.
        request = SearchRequest(params=SearchParams(query="mcp", limit=3))
        result = await client.session.send_request(cast("types.ClientRequest", request), SearchResult)
        assert result.items == ["mcp-0", "mcp-1", "mcp-2"], result


if __name__ == "__main__":
    run_client(main)
