"""Simple task server demonstrating MCP tasks over streamable HTTP."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import click
import uvicorn
from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount


async def handle_list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="long_running_task",
                description="A task that takes a few seconds to complete with status updates",
                input_schema={"type": "object", "properties": {}},
                execution=types.ToolExecution(task_support=types.TASK_REQUIRED),
            )
        ]
    )


async def handle_call_tool(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult | types.CreateTaskResult:
    """Dispatch tool calls to their handlers."""
    if params.name == "long_running_task":
        ctx.experimental.validate_task_mode(types.TASK_REQUIRED)

        async def work(task: ServerTaskContext) -> types.CallToolResult:
            await task.update_status("Starting work...")
            await anyio.sleep(1)

            await task.update_status("Processing step 1...")
            await anyio.sleep(1)

            await task.update_status("Processing step 2...")
            await anyio.sleep(1)

            return types.CallToolResult(content=[types.TextContent(type="text", text="Task completed!")])

        return await ctx.experimental.run_task(work)

    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"Unknown tool: {params.name}")],
        is_error=True,
    )


server = Server(
    "simple-task-server",
    on_list_tools=handle_list_tools,
    on_call_tool=handle_call_tool,
)

# One-line setup: auto-registers get_task, get_task_result, list_tasks, cancel_task
server.experimental.enable_tasks()


@click.command()
@click.option("--port", default=8000, help="Port to listen on")
def main(port: int) -> int:
    session_manager = StreamableHTTPSessionManager(app=server)

    @asynccontextmanager
    async def app_lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    starlette_app = Starlette(
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        lifespan=app_lifespan,
    )

    print(f"Starting server on http://localhost:{port}/mcp")
    uvicorn.run(starlette_app, host="127.0.0.1", port=port)
    return 0
