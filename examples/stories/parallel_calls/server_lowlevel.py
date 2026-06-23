"""Rendezvous tool on the lowlevel `Server`, proving concurrent dispatch without `MCPServer`."""

from collections import defaultdict
from typing import Any

import anyio

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import run_server_from_args

MEET_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tag": {"type": "string"},
        "party": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tag", "party"],
}


def build_server() -> Server[Any]:
    arrivals: dict[str, anyio.Event] = defaultdict(anyio.Event)

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="meet", description="Rendezvous with peers.", input_schema=MEET_INPUT_SCHEMA)]
        )

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "meet"
        assert params.arguments is not None
        tag = params.arguments["tag"]
        assert isinstance(tag, str)
        arrivals[tag].set()
        for peer in params.arguments["party"]:
            await arrivals[peer].wait()
        await ctx.session.report_progress(1.0, total=1.0, message=tag)
        return types.CallToolResult(content=[types.TextContent(text=tag)])

    return Server("parallel-calls-example", on_list_tools=list_tools, on_call_tool=call_tool)


if __name__ == "__main__":
    run_server_from_args(build_server)
