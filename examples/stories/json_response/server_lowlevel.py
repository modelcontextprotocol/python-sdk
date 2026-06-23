"""Serve over Streamable HTTP with JSON responses (lowlevel API)."""

from typing import Any

from starlette.applications import Starlette

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import NO_DNS_REBIND, run_app_from_args

GREET_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}


def build_app() -> Starlette:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="greet",
                    description="Report progress mid-call, then return a greeting.",
                    input_schema=GREET_INPUT_SCHEMA,
                )
            ]
        )

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "greet" and params.arguments is not None
        await ctx.session.report_progress(0.5, total=1.0, message="halfway")
        text = f"Hello, {params.arguments['name']}!"
        return types.CallToolResult(content=[types.TextContent(text=text)], structured_content={"result": text})

    server = Server("json-response-example", on_list_tools=list_tools, on_call_tool=call_tool)
    return server.streamable_http_app(json_response=True, transport_security=NO_DNS_REBIND)


if __name__ == "__main__":
    run_app_from_args(build_app)
