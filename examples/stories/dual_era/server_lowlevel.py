"""One lowlevel Server factory that serves both the 2025 handshake era and the 2026 stateless era."""

from typing import Any

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.shared.version import MODERN_PROTOCOL_VERSIONS
from stories._hosting import run_server_from_args

GREET_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}


def build_server() -> Server[Any]:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="greet",
                    description="Greet the caller and report which protocol era served the request.",
                    input_schema=GREET_INPUT_SCHEMA,
                ),
            ]
        )

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "greet" and params.arguments is not None
        era = "modern" if ctx.protocol_version in MODERN_PROTOCOL_VERSIONS else "legacy"
        text = f"Hello, {params.arguments['name']}! (served on the {era} era at {ctx.protocol_version})"
        return types.CallToolResult(content=[types.TextContent(text=text)])

    # The same factory serves both eras with no configuration. Which era a request is
    # on is decided by the entry point / transport, never by the server.
    return Server(
        "dual-era-example",
        instructions="A small dual-era demo server.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


if __name__ == "__main__":
    run_server_from_args(build_server)
