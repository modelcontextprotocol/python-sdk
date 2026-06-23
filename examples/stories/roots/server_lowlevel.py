"""Roots primitive (lowlevel API): the same server→client round-trip, hand-built."""

from typing import Any

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import run_server_from_args


def build_server() -> Server[Any]:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="show_roots",
                    description="Return the filesystem roots the client has exposed.",
                    input_schema={"type": "object"},
                ),
            ]
        )

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "show_roots"
        result = await ctx.session.list_roots()  # pyright: ignore[reportDeprecated]
        lines = [f"{root.uri} ({root.name or 'unnamed'})" for root in result.roots]
        return types.CallToolResult(content=[types.TextContent(text="\n".join(lines))])

    return Server("roots-example", on_list_tools=list_tools, on_call_tool=call_tool)


if __name__ == "__main__":
    run_server_from_args(build_server)
