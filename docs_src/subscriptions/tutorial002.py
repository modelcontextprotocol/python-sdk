from typing import Any

import mcp_types as types

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.subscriptions import InMemorySubscriptionBus, ListenHandler, ResourceUpdated

bus = InMemorySubscriptionBus()

NOTES = {"todo": "buy milk"}

EDIT_NOTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "text": {"type": "string"}},
    "required": ["name", "text"],
}


async def list_tools(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[types.Tool(name="edit_note", description="Replace a note's text.", input_schema=EDIT_NOTE_SCHEMA)]
    )


async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
    args = params.arguments or {}
    NOTES[args["name"]] = args["text"]
    await bus.publish(ResourceUpdated(uri=f"note://{args['name']}"))
    return types.CallToolResult(content=[types.TextContent(type="text", text="saved")])


server = Server(
    "notebook",
    on_list_tools=list_tools,
    on_call_tool=call_tool,
    on_subscriptions_listen=ListenHandler(bus),
)
