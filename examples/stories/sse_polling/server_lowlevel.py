"""SEP-1699 polling on the lowlevel `Server`: close the request's SSE stream mid-handler."""

from typing import Any

from starlette.applications import Starlette

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import NO_DNS_REBIND, run_app_from_args
from stories.sse_polling.event_store import InMemoryEventStore

_TOOL = types.Tool(
    name="long_operation",
    description="Emit progress, close the SSE stream, emit more, return.",
    input_schema={"type": "object", "properties": {}},
)


def build_app() -> Starlette:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[_TOOL])

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "long_operation"
        await ctx.session.report_progress(0.5, total=1.0, message="before-close")
        # The transport only wires this callback when an event_store is configured and the
        # negotiated version is in the 2025 era; it is None otherwise.
        if ctx.close_sse_stream is not None:
            await ctx.close_sse_stream()
        await ctx.session.report_progress(1.0, total=1.0, message="after-close")
        return types.CallToolResult(content=[types.TextContent(text="resumed")])

    server = Server("sse-polling-example", on_list_tools=list_tools, on_call_tool=call_tool)
    return server.streamable_http_app(
        event_store=InMemoryEventStore(),
        retry_interval=0,
        transport_security=NO_DNS_REBIND,
    )


if __name__ == "__main__":
    run_app_from_args(build_app)
