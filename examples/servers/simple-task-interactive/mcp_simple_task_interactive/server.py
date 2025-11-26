"""Simple interactive task server demonstrating elicitation and sampling."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import anyio
import click
import mcp.types as types
import uvicorn
from anyio.abc import TaskGroup
from mcp.server.lowlevel import Server
from mcp.server.session import ServerSession
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.experimental.tasks import (
    InMemoryTaskMessageQueue,
    InMemoryTaskStore,
    TaskResultHandler,
    TaskSession,
    task_execution,
)
from starlette.applications import Starlette
from starlette.routing import Mount


@dataclass
class AppContext:
    task_group: TaskGroup
    store: InMemoryTaskStore
    queue: InMemoryTaskMessageQueue
    handler: TaskResultHandler
    # Track sessions that have been configured (session ID -> bool)
    configured_sessions: dict[int, bool]


@asynccontextmanager
async def lifespan(server: Server[AppContext, Any]) -> AsyncIterator[AppContext]:
    store = InMemoryTaskStore()
    queue = InMemoryTaskMessageQueue()
    handler = TaskResultHandler(store, queue)
    async with anyio.create_task_group() as tg:
        yield AppContext(
            task_group=tg,
            store=store,
            queue=queue,
            handler=handler,
            configured_sessions={},
        )
    store.cleanup()
    queue.cleanup()


server: Server[AppContext, Any] = Server("simple-task-interactive", lifespan=lifespan)


def ensure_handler_configured(session: ServerSession, app: AppContext) -> None:
    """Ensure the task result handler is configured for this session (once)."""
    session_id = id(session)
    if session_id not in app.configured_sessions:
        session.add_response_router(app.handler)
        app.configured_sessions[session_id] = True


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


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent] | types.CreateTaskResult:
    ctx = server.request_context
    app = ctx.lifespan_context

    # Validate task mode
    ctx.experimental.validate_task_mode(types.TASK_REQUIRED)

    # Ensure handler is configured for response routing
    ensure_handler_configured(ctx.session, app)

    # Create task
    metadata = ctx.experimental.task_metadata
    assert metadata is not None
    task = await app.store.create_task(metadata)

    if name == "confirm_delete":
        filename = arguments.get("filename", "unknown.txt")
        print(f"\n[Server] confirm_delete called for '{filename}'")
        print(f"[Server] Task created: {task.taskId}")

        async def do_confirm() -> None:
            async with task_execution(task.taskId, app.store) as task_ctx:
                task_session = TaskSession(
                    session=ctx.session,
                    task_id=task.taskId,
                    store=app.store,
                    queue=app.queue,
                )

                print("[Server] Sending elicitation request to client...")
                result = await task_session.elicit(
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
                await task_ctx.complete(
                    types.CallToolResult(content=[types.TextContent(type="text", text=text)]),
                    notify=True,
                )

        app.task_group.start_soon(do_confirm)

    elif name == "write_haiku":
        topic = arguments.get("topic", "nature")
        print(f"\n[Server] write_haiku called for topic '{topic}'")
        print(f"[Server] Task created: {task.taskId}")

        async def do_haiku() -> None:
            async with task_execution(task.taskId, app.store) as task_ctx:
                task_session = TaskSession(
                    session=ctx.session,
                    task_id=task.taskId,
                    store=app.store,
                    queue=app.queue,
                )

                print("[Server] Sending sampling request to client...")
                result = await task_session.create_message(
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
                print("[Server] Completing task with haiku")
                await task_ctx.complete(
                    types.CallToolResult(content=[types.TextContent(type="text", text=f"Haiku:\n{haiku}")]),
                    notify=True,
                )

        app.task_group.start_soon(do_haiku)

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
        lastUpdatedAt=task.lastUpdatedAt,
        ttl=task.ttl,
        pollInterval=task.pollInterval,
    )


@server.experimental.get_task_result()
async def handle_get_task_result(
    request: types.GetTaskPayloadRequest,
) -> types.GetTaskPayloadResult:
    ctx = server.request_context
    app = ctx.lifespan_context

    # Ensure handler is configured for this session
    ensure_handler_configured(ctx.session, app)

    return await app.handler.handle(request, ctx.session, ctx.request_id)


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
