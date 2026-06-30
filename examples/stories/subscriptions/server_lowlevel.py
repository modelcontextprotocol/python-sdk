"""The same notebook against the low-level Server: an explicit bus + ListenHandler."""

from typing import Any

import mcp_types as types

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.subscriptions import (
    InMemorySubscriptionBus,
    ListenHandler,
    ResourceUpdated,
    ToolsListChanged,
)
from stories._hosting import run_server_from_args

EDIT_NOTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "text": {"type": "string"}},
    "required": ["name", "text"],
}
EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}
SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}


def build_server() -> Server[Any]:
    # The bus lives wherever your handlers can reach it; the lifespan is the
    # natural home in a bigger app. The closure is enough here.
    bus = InMemorySubscriptionBus()
    notes = {"todo": "buy milk", "journal": "day one"}
    search_enabled = False

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        tools = [
            types.Tool(name="edit_note", description="Replace a note's text.", input_schema=EDIT_NOTE_SCHEMA),
            types.Tool(name="enable_search", description="Register the search tool.", input_schema=EMPTY_SCHEMA),
        ]
        if search_enabled:
            tools.append(types.Tool(name="search", description="Find notes.", input_schema=SEARCH_SCHEMA))
        return types.ListToolsResult(tools=tools)

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        nonlocal search_enabled
        args = params.arguments or {}
        if params.name == "edit_note":
            notes[args["name"]] = args["text"]
            await bus.publish(ResourceUpdated(uri=f"note://{args['name']}"))
            return types.CallToolResult(content=[types.TextContent(text="saved")])
        if params.name == "enable_search":
            search_enabled = True
            await bus.publish(ToolsListChanged())
            return types.CallToolResult(content=[types.TextContent(text="search is live")])
        assert params.name == "search"
        matches = [name for name, text in notes.items() if args["query"] in text]
        return types.CallToolResult(content=[types.TextContent(text=", ".join(matches))])

    return Server(
        "subscriptions-example",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_subscriptions_listen=ListenHandler(bus),
    )


if __name__ == "__main__":
    run_server_from_args(build_server)
