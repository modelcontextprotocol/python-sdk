"""Read the negotiated protocol version inside a lowlevel handler (initialize handshake)."""

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
                    name="protocol_info",
                    description="Return the protocol version this connection negotiated.",
                    input_schema={"type": "object"},
                )
            ]
        )

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "protocol_info"
        return types.CallToolResult(content=[types.TextContent(text=ctx.protocol_version)])

    return Server("custom-version-example", on_list_tools=list_tools, on_call_tool=call_tool)


if __name__ == "__main__":
    run_server_from_args(build_server)
