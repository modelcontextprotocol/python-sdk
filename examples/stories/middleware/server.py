"""Dispatch-layer middleware via the `middleware` list on lowlevel `Server`.

`MCPServer` has no public middleware accessor yet, so this story is lowlevel-only.
"""

import json
from typing import Any

import mcp_types as types

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import run_server_from_args


def build_server() -> Server[Any]:
    log: list[str] = []

    async def record_calls(ctx: ServerRequestContext[Any], call_next: CallNext) -> HandlerResult:
        log.append(ctx.method)
        try:
            return await call_next(ctx)
        finally:
            log.append(f"{ctx.method}:done")

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="audit_log",
                    description="Return every method the middleware has observed so far.",
                    input_schema={"type": "object"},
                )
            ]
        )

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "audit_log"
        snapshot = list(log)
        return types.CallToolResult(
            content=[types.TextContent(text=json.dumps(snapshot))],
            structured_content={"result": snapshot},
        )

    server = Server("middleware-example", on_list_tools=list_tools, on_call_tool=call_tool)
    server.middleware.append(record_calls)
    return server


if __name__ == "__main__":
    run_server_from_args(build_server)
