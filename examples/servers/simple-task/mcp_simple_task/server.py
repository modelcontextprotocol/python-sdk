"""Simple task server demonstrating MCP tasks over streamable HTTP."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import anyio
import click
import mcp.types as types
from anyio.abc import TaskGroup
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.experimental.tasks import InMemoryTaskStore, task_execution
from starlette.applications import Starlette
from starlette.routing import Mount


@dataclass
class AppContext:
    task_group: TaskGroup
    store: InMemoryTaskStore


@asynccontextmanager
async def lifespan(server: Server[AppContext, Any]) -> AsyncIterator[AppContext]:
    store = InMemoryTaskStore()
    async with anyio.create_task_group() as tg:
        yield AppContext(task_group=tg, store=store)
    store.cleanup()


server: Server[AppContext, Any] = Server("simple-task-server", lifespan=lifespan)


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="long_running_task",
            description="A task that takes a few seconds to complete with status updates",
            inputSchema={"type": "object", "properties": {}},
            execution=types.ToolExecution(task="always"),
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent] | types.CreateTaskResult:
    ctx = server.request_context
    app = ctx.lifespan_context

    # Validate task mode - raises McpError(-32601) if client didn't use task augmentation
    ctx.experimental.validate_task_mode("always")

    # Create the task
    metadata = ctx.experimental.task_metadata
    assert metadata is not None
    task = await app.store.create_task(metadata)

    # Spawn background work
    async def do_work() -> None:
        async with task_execution(task.taskId, app.store) as task_ctx:
            await task_ctx.update_status("Starting work...")
            await anyio.sleep(1)

            await task_ctx.update_status("Processing step 1...")
            await anyio.sleep(1)

            await task_ctx.update_status("Processing step 2...")
            await anyio.sleep(1)

            await task_ctx.complete(
                types.CallToolResult(content=[types.TextContent(type="text", text="Task completed!")])
            )

    app.task_group.start_soon(do_work)
    return types.CreateTaskResult(task=task)


@server.experimental.get_task()
async def handle_get_task(request: types.GetTaskRequest) -> types.GetTaskResult:
    app = server.request_context.lifespan_context
    task = await app.store.get_task(request.params.taskId)
    if task is None:
        raise ValueError(f"Task {request.params.taskId} not found")
    return types.GetTaskResult(
        taskId=task.taskId,
        status=task.status,
        statusMessage=task.statusMessage,
        createdAt=task.createdAt,
        ttl=task.ttl,
        pollInterval=task.pollInterval,
    )


@server.experimental.get_task_result()
async def handle_get_task_result(request: types.GetTaskPayloadRequest) -> types.GetTaskPayloadResult:
    app = server.request_context.lifespan_context
    result = await app.store.get_result(request.params.taskId)
    if result is None:
        raise ValueError(f"Result for task {request.params.taskId} not found")
    assert isinstance(result, types.CallToolResult)
    return types.GetTaskPayloadResult(**result.model_dump())


@click.command()
@click.option("--port", default=8000, help="Port to listen on")
def main(port: int) -> int:
    import uvicorn

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
