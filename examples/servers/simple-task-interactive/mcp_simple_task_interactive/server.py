"""Simple interactive task server demonstrating elicitation and sampling.

This example shows the simplified task API where:
- server.experimental.enable_tasks() sets up all infrastructure
- ctx.experimental.run_task() handles task lifecycle automatically
- ServerTaskContext.elicit() and ServerTaskContext.create_message() queue requests properly
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import click
import mcp.types as types
import uvicorn
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount

server = Server("simple-task-interactive")

# Enable task support - this auto-registers all handlers
server.experimental.enable_tasks()


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="confirm_delete",
            description="Asks for confirmation before deleting (demonstrates elicitation)",
            inputSchema={
                "type": "object",
                "properties": {"filename": {"type": "string"}},
            },
            execution=types.ToolExecution(taskSupport=types.TASK_REQUIRED),
        ),
        types.Tool(
            name="write_haiku",
            description="Asks LLM to write a haiku (demonstrates sampling)",
            inputSchema={"type": "object", "properties": {"topic": {"type": "string"}}},
            execution=types.ToolExecution(taskSupport=types.TASK_REQUIRED),
        ),
    ]


async def handle_confirm_delete(arguments: dict[str, Any]) -> types.CreateTaskResult:
    """Handle the confirm_delete tool - demonstrates elicitation."""
    ctx = server.request_context
    ctx.experimental.validate_task_mode(types.TASK_REQUIRED)

    filename = arguments.get("filename", "unknown.txt")
    print(f"\n[Server] confirm_delete called for '{filename}'")

    async def work(task: ServerTaskContext) -> types.CallToolResult:
        print(f"[Server] Task {task.task_id} starting elicitation...")

        result = await task.elicit(
            message=f"Are you sure you want to delete '{filename}'?",
            requestedSchema={
                "type": "object",
                "properties": {"confirm": {"type": "boolean"}},
                "required": ["confirm"],
            },
        )

        print(f"[Server] Received elicitation response: action={result.action}, content={result.content}")

        if result.action == "accept" and result.content:
            confirmed = result.content.get("confirm", False)
            text = f"Deleted '{filename}'" if confirmed else "Deletion cancelled"
        else:
            text = "Deletion cancelled"

        print(f"[Server] Completing task with result: {text}")
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)])

    return await ctx.experimental.run_task(work)


async def handle_write_haiku(arguments: dict[str, Any]) -> types.CreateTaskResult:
    """Handle the write_haiku tool - demonstrates sampling."""
    ctx = server.request_context
    ctx.experimental.validate_task_mode(types.TASK_REQUIRED)

    topic = arguments.get("topic", "nature")
    print(f"\n[Server] write_haiku called for topic '{topic}'")

    async def work(task: ServerTaskContext) -> types.CallToolResult:
        print(f"[Server] Task {task.task_id} starting sampling...")

        result = await task.create_message(
            messages=[
                types.SamplingMessage(
                    role="user",
                    content=types.TextContent(type="text", text=f"Write a haiku about {topic}"),
                )
            ],
            max_tokens=50,
        )

        haiku = "No response"
        if isinstance(result.content, types.TextContent):
            haiku = result.content.text

        print(f"[Server] Received sampling response: {haiku[:50]}...")
        return types.CallToolResult(content=[types.TextContent(type="text", text=f"Haiku:\n{haiku}")])

    return await ctx.experimental.run_task(work)


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult | types.CreateTaskResult:
    """Dispatch tool calls to their handlers."""
    if name == "confirm_delete":
        return await handle_confirm_delete(arguments)
    elif name == "write_haiku":
        return await handle_write_haiku(arguments)
    else:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Unknown tool: {name}")],
            isError=True,
        )


def create_app(session_manager: StreamableHTTPSessionManager) -> Starlette:
    @asynccontextmanager
    async def app_lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    return Starlette(
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        lifespan=app_lifespan,
    )


@click.command()
@click.option("--port", default=8000, help="Port to listen on")
def main(port: int) -> int:
    session_manager = StreamableHTTPSessionManager(app=server)
    starlette_app = create_app(session_manager)
    print(f"Starting server on http://localhost:{port}/mcp")
    uvicorn.run(starlette_app, host="127.0.0.1", port=port)
    return 0
