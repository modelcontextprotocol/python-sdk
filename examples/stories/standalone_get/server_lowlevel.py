"""Sessionful Streamable HTTP (lowlevel `Server`): tool-triggered `list_changed` over the standalone GET stream."""

import itertools
from typing import Any

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import run_server_from_args

ADD_NOTE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"content": {"type": "string"}},
    "required": ["content"],
}


def build_server() -> Server[Any]:
    counter = itertools.count(1)
    resources: list[types.Resource] = [types.Resource(uri="note://initial", name="initial", mime_type="text/plain")]

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="add_note", input_schema=ADD_NOTE_INPUT_SCHEMA)])

    async def list_resources(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=list(resources))

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "add_note" and params.arguments is not None
        name = f"note-{next(counter)}"
        resources.append(types.Resource(uri=f"note://{name}", name=name, mime_type="text/plain"))
        await ctx.session.send_resource_list_changed()
        return types.CallToolResult(content=[types.TextContent(text=f"registered {name}")])

    return Server(
        "standalone-get-example",
        on_list_tools=list_tools,
        on_list_resources=list_resources,
        on_call_tool=call_tool,
    )


if __name__ == "__main__":
    run_server_from_args(build_server)
