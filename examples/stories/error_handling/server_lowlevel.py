"""Two error channels on lowlevel.Server: return is_error=True yourself, or raise MCPError."""

from typing import Any

import mcp_types as types

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import MCPError
from stories._hosting import run_server_from_args

_TOOLS = [
    types.Tool(name="divide", description="Divide a by b.", input_schema={"type": "object"}),
    types.Tool(name="restricted", description="Always rejects.", input_schema={"type": "object"}),
]


def build_server() -> Server[Any]:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=_TOOLS)

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        args = params.arguments or {}
        if params.name == "divide":
            a, b = float(args["a"]), float(args["b"])
            if b == 0:
                # Execution error: build the is_error result yourself.
                return types.CallToolResult(
                    content=[types.TextContent(text="cannot divide by zero")],
                    is_error=True,
                )
            return types.CallToolResult(content=[types.TextContent(text=str(a / b))])
        if params.name == "restricted":
            # Protocol error: raise MCPError; the dispatcher serialises it as a
            # JSON-RPC error response with this code/message/data.
            raise MCPError(code=types.INVALID_PARAMS, message="this tool is gated", data={"reason": "demo"})
        raise MCPError(code=types.INVALID_PARAMS, message=f"Unknown tool: {params.name}")

    return Server("error-handling-example", on_list_tools=list_tools, on_call_tool=call_tool)


if __name__ == "__main__":
    run_server_from_args(build_server)
