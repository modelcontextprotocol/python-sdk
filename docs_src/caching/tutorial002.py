from typing import Any

from mcp_types import ListToolsResult, PaginatedRequestParams, Tool

from mcp.server import CacheHint, Server, ServerRequestContext

TOOLS = [Tool(name="forecast", input_schema={"type": "object"})]


async def list_tools(ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=TOOLS, ttl_ms=1_000)


server = Server(
    "Weather",
    on_list_tools=list_tools,
    cache_hints={"tools/list": CacheHint(ttl_ms=60_000, scope="public")},
)
