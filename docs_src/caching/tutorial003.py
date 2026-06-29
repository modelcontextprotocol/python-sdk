from typing import Any

from mcp_types import ListToolsResult, PaginatedRequestParams, Tool

from mcp import Client
from mcp.client import CacheConfig
from mcp.server import CacheHint, Server, ServerRequestContext

fetches = 0
now = 1_000_000.0


async def list_tools(ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None) -> ListToolsResult:
    global fetches
    fetches += 1
    return ListToolsResult(tools=[Tool(name="forecast", input_schema={"type": "object"})])


server = Server(
    "Weather",
    on_list_tools=list_tools,
    cache_hints={"tools/list": CacheHint(ttl_ms=60_000, scope="public")},
)


async def main() -> None:
    global now
    async with Client(server, cache=CacheConfig(clock=lambda: now)) as client:
        await client.list_tools()  # fetch 1
        await client.list_tools()  # fresh for 60s: served from the cache
        now += 60.0
        await client.list_tools()  # the TTL ran out: fetch 2
        await client.list_tools(cache_mode="refresh")  # skip the cache read: fetch 3
        print(f"4 calls, {fetches} fetches")
