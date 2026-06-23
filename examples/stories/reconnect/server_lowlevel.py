"""A small modern server whose DiscoverResult a client persists for zero-RTT reconnect (lowlevel API)."""

from typing import Any

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import run_server_from_args

ADD = types.Tool(
    name="add",
    description="Add two integers.",
    input_schema={
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    },
)


def build_server() -> Server[Any]:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[ADD])

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.arguments is not None
        if params.name == "add":
            total = int(params.arguments["a"]) + int(params.arguments["b"])
            return types.CallToolResult(
                content=[types.TextContent(text=str(total))],
                structured_content={"result": total},
            )
        raise NotImplementedError

    return Server(
        "reconnect-example",
        version="1.0.0",
        instructions="Call add(a, b) to sum two integers.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


if __name__ == "__main__":
    run_server_from_args(build_server)
