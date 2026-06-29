from mcp import Client
from mcp.server import CacheHint, MCPServer

mcp = MCPServer("Weather", cache_hints={"tools/list": CacheHint(ttl_ms=60_000, scope="public")})


@mcp.tool()
def forecast(city: str) -> str:
    return f"Sunny in {city}"


async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        print(f"{len(tools.tools)} tools, fresh for {tools.ttl_ms / 1000:.0f}s, scope={tools.cache_scope}")
