"""Exported era classifier (lowlevel API): the same dual-era app + CORS — the predicate stays in `server.py`."""

from typing import Any

import mcp_types as types
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import NO_DNS_REBIND, run_app_from_args

from .server import MCP_ALLOWED_HEADERS, MCP_ALLOWED_METHODS, MCP_EXPOSED_HEADERS

WHICH_ARM = types.Tool(
    name="which_arm",
    description="Report which era the built-in router dispatched this request to.",
    input_schema={"type": "object", "properties": {}},
)


def build_app() -> Starlette:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[WHICH_ARM])

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "which_arm"
        arm = "modern" if ctx.protocol_version in MODERN_PROTOCOL_VERSIONS else "legacy"
        return types.CallToolResult(content=[types.TextContent(text=arm)])

    server = Server("legacy-routing-example", on_list_tools=list_tools, on_call_tool=call_tool)

    app = server.streamable_http_app(transport_security=NO_DNS_REBIND)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=MCP_ALLOWED_METHODS,
        allow_headers=MCP_ALLOWED_HEADERS,
        expose_headers=MCP_EXPOSED_HEADERS,
    )
    return app


if __name__ == "__main__":
    run_app_from_args(build_app)
