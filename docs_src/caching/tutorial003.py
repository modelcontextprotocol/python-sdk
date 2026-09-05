from dataclasses import dataclass

import anyio

from mcp import Client
from mcp.client import CacheConfig
from mcp.types import ListToolsResult


@dataclass
class Clock:
    now: float = 0.0


clock = Clock()  # advanced by hand below, so the TTL runs out without sleeping


async def run(client: Client) -> ListToolsResult:
    tools = await client.list_tools()  # fetch 1
    await client.list_tools()  # still fresh: served from the cache
    clock.now += 2
    await client.list_tools()  # past the one-second TTL: fetch 2
    await client.list_tools(cache_mode="refresh")  # skip the cache read: fetch 3
    return tools


async def main() -> None:
    async with Client("http://localhost:8000/mcp", cache=CacheConfig(clock=lambda: clock.now)) as client:
        tools = await run(client)
        print(tools.ttl_ms, tools.cache_scope)


if __name__ == "__main__":
    anyio.run(main)
