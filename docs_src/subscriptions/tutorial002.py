from typing import Any

import mcp_types as types

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.subscriptions import InMemorySubscriptionBus, ListenHandler, ResourceUpdated

bus = InMemorySubscriptionBus()
listen_handler = ListenHandler(bus)

BOARD = {"design": False, "build": False}

COMPLETE_TASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"task": {"type": "string"}},
    "required": ["task"],
}


async def read_resource(
    ctx: ServerRequestContext[Any], params: types.ReadResourceRequestParams
) -> types.ReadResourceResult:
    board = "\n".join(f"[{'x' if done else ' '}] {task}" for task, done in BOARD.items())
    return types.ReadResourceResult(contents=[types.TextResourceContents(uri=params.uri, text=board)])


async def list_tools(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[types.Tool(name="complete_task", description="Mark a task done.", input_schema=COMPLETE_TASK_SCHEMA)]
    )


async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
    args = params.arguments or {}
    BOARD[args["task"]] = True
    await bus.publish(ResourceUpdated(uri="board://sprint"))
    return types.CallToolResult(content=[types.TextContent(type="text", text="done")])


server = Server(
    "sprint-board",
    on_read_resource=read_resource,
    on_list_tools=list_tools,
    on_call_tool=call_tool,
    on_subscriptions_listen=listen_handler,
)
