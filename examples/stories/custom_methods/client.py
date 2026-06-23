"""Send a vendor-prefixed request via the `client.session` escape hatch."""

from typing import Literal, cast

from mcp import types
from mcp.client import Client
from stories._harness import connect_from_args, run_client


class SearchParams(types.RequestParams):
    query: str
    limit: int = 10


class SearchRequest(types.Request[SearchParams, Literal["acme/search"]]):
    method: Literal["acme/search"] = "acme/search"
    params: SearchParams


class SearchResult(types.Result):
    items: list[str]


async def scenario(client: Client) -> None:
    # `Client` only exposes spec-defined verbs. For vendor methods, drop one
    # layer to `client.session` — the sanctioned escape hatch. `send_request`
    # is typed against the closed `ClientRequest` union, hence the cast; at
    # runtime the body only calls `.model_dump()` and the unknown method skips
    # the per-spec result-validation registry.
    request = SearchRequest(params=SearchParams(query="mcp", limit=3))
    result = await client.session.send_request(cast("types.ClientRequest", request), SearchResult)
    assert result.items == ["mcp-0", "mcp-1", "mcp-2"], result


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__))
