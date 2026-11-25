from mcp.server import CacheHint, MCPServer

mcp = MCPServer(
    "Weather",
    cache_hints={
        "tools/list": CacheHint(ttl_ms=60_000, scope="public"),
        "resources/read": CacheHint(ttl_ms=5_000),
    },
)


@mcp.tool()
def forecast(city: str) -> str:
    return f"Sunny in {city}"


@mcp.resource("config://units")
def units() -> str:
    return "metric"
