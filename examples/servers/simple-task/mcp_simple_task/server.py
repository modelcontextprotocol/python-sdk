"""Simple task server demonstrating MCP tasks over streamable HTTP."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import click
import mcp.types as types
import uvicorn
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount

server = Server("simple-task-server")

# One-line setup: auto-registers get_task, get_task_result, list_tasks, cancel_task
server.experimental.enable_tasks()


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="long_running_task",
            description="A task that takes a few seconds to complete with status updates",
            inputSchema={"type": "object", "properties": {}},
            execution=types.ToolExecution(taskSupport=types.TASK_REQUIRED),
        )
    ]


async def handle_long_running_task(arguments: dict[str, Any]) -> types.CreateTaskResult:
    """Handle the long_running_task tool - demonstrates status updates."""
    ctx = server.request_context
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


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult | types.CreateTaskResult:
    """Dispatch tool calls to their handlers."""
    if name == "long_running_task":
        return await handle_long_running_task(arguments)
    else:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Unknown tool: {name}")],
            isError=True,
        )


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
