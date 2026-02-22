"""End-to-end integration tests for tasks functionality.

These tests demonstrate the full task lifecycle:
1. Client sends task-augmented request (tools/call with task metadata)
2. Server creates task and returns CreateTaskResult immediately
3. Background work executes (using task_execution context manager)
4. Client polls with tasks/get
5. Client retrieves result with tasks/result
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import anyio
import pytest
from anyio import Event
from anyio.abc import TaskGroup

from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.shared.experimental.tasks.helpers import task_execution
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    CreateTaskResult,
    GetTaskPayloadRequestParams,
    GetTaskPayloadResult,
    GetTaskRequestParams,
    GetTaskResult,
    ListTasksResult,
    ListToolsResult,
    PaginatedRequestParams,
    TaskMetadata,
    TextContent,
)

pytestmark = pytest.mark.anyio


@dataclass
class AppContext:
    """Application context passed via lifespan_context."""

    task_group: TaskGroup
    store: InMemoryTaskStore
    task_done_events: dict[str, Event] = field(default_factory=lambda: {})


def _make_lifespan(store: InMemoryTaskStore, task_done_events: dict[str, Event]):
    @asynccontextmanager
    async def app_lifespan(server: Server[AppContext]) -> AsyncIterator[AppContext]:
        async with anyio.create_task_group() as tg:
            yield AppContext(task_group=tg, store=store, task_done_events=task_done_events)

    return app_lifespan


async def test_task_lifecycle_with_task_execution() -> None:
    """Test the complete task lifecycle using the task_execution pattern."""
    store = InMemoryTaskStore()
    task_done_events: dict[str, Event] = {}

    async def handle_list_tools(
        ctx: ServerRequestContext[AppContext], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        raise NotImplementedError

    async def handle_call_tool(
        ctx: ServerRequestContext[AppContext], params: CallToolRequestParams
    ) -> CallToolResult | CreateTaskResult:
        app = ctx.session_lifespan_context
        if params.name == "process_data" and ctx.experimental.is_task:
            task_metadata = ctx.experimental.task_metadata
            assert task_metadata is not None
            task = await app.store.create_task(task_metadata)

            done_event = Event()
            app.task_done_events[task.task_id] = done_event

            async def do_work() -> None:
                async with task_execution(task.task_id, app.store) as task_ctx:
                    await task_ctx.update_status("Processing input...")
                    input_value = (params.arguments or {}).get("input", "")
                    result_text = f"Processed: {input_value.upper()}"
                    await task_ctx.complete(CallToolResult(content=[TextContent(type="text", text=result_text)]))
                done_event.set()

            app.task_group.start_soon(do_work)
            return CreateTaskResult(task=task)

        raise NotImplementedError

    async def handle_get_task(ctx: ServerRequestContext[AppContext], params: GetTaskRequestParams) -> GetTaskResult:
        app = ctx.session_lifespan_context
        task = await app.store.get_task(params.task_id)
        assert task is not None, f"Test setup error: task {params.task_id} should exist"
        return GetTaskResult(
            task_id=task.task_id,
            status=task.status,
            status_message=task.status_message,
            created_at=task.created_at,
            last_updated_at=task.last_updated_at,
            ttl=task.ttl,
            poll_interval=task.poll_interval,
        )

    async def handle_get_task_result(
        ctx: ServerRequestContext[AppContext], params: GetTaskPayloadRequestParams
    ) -> GetTaskPayloadResult:
        app = ctx.session_lifespan_context
        result = await app.store.get_result(params.task_id)
        assert result is not None, f"Test setup error: result for {params.task_id} should exist"
        assert isinstance(result, CallToolResult)
        return GetTaskPayloadResult(**result.model_dump())

    async def handle_list_tasks(
        ctx: ServerRequestContext[AppContext], params: PaginatedRequestParams | None
    ) -> ListTasksResult:
        raise NotImplementedError

    server: Server[AppContext] = Server(
        "test-tasks",
        lifespan=_make_lifespan(store, task_done_events),
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )
    server.experimental.enable_tasks(
        on_get_task=handle_get_task,
        on_task_result=handle_get_task_result,
        on_list_tasks=handle_list_tasks,
    )

    async with Client(server) as client:
        # Step 1: Send task-augmented tool call
        create_result = await client.session.send_request(
            CallToolRequest(
                params=CallToolRequestParams(
                    name="process_data",
                    arguments={"input": "hello world"},
                    task=TaskMetadata(ttl=60000),
                ),
            ),
            CreateTaskResult,
        )

        assert isinstance(create_result, CreateTaskResult)
        assert create_result.task.status == "working"
        task_id = create_result.task.task_id

        # Step 2: Wait for task to complete
        await task_done_events[task_id].wait()

        task_status = await client.session.experimental.get_task(task_id)
        assert task_status.task_id == task_id
        assert task_status.status == "completed"

        # Step 3: Retrieve the actual result
        task_result = await client.session.experimental.get_task_result(task_id, CallToolResult)

        assert len(task_result.content) == 1
        content = task_result.content[0]
        assert isinstance(content, TextContent)
        assert content.text == "Processed: HELLO WORLD"


async def test_task_auto_fails_on_exception() -> None:
    """Test that task_execution automatically fails the task on unhandled exception."""
    store = InMemoryTaskStore()
    task_done_events: dict[str, Event] = {}

    async def handle_list_tools(
        ctx: ServerRequestContext[AppContext], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        raise NotImplementedError

    async def handle_call_tool(
        ctx: ServerRequestContext[AppContext], params: CallToolRequestParams
    ) -> CallToolResult | CreateTaskResult:
        app = ctx.session_lifespan_context
        if params.name == "failing_task" and ctx.experimental.is_task:
            task_metadata = ctx.experimental.task_metadata
            assert task_metadata is not None
            task = await app.store.create_task(task_metadata)

            done_event = Event()
            app.task_done_events[task.task_id] = done_event

            async def do_failing_work() -> None:
                async with task_execution(task.task_id, app.store) as task_ctx:
                    await task_ctx.update_status("About to fail...")
                    raise RuntimeError("Something went wrong!")
                # This line is reached because task_execution suppresses the exception
                done_event.set()

            app.task_group.start_soon(do_failing_work)
            return CreateTaskResult(task=task)

        raise NotImplementedError

    async def handle_get_task(ctx: ServerRequestContext[AppContext], params: GetTaskRequestParams) -> GetTaskResult:
        app = ctx.session_lifespan_context
        task = await app.store.get_task(params.task_id)
        assert task is not None, f"Test setup error: task {params.task_id} should exist"
        return GetTaskResult(
            task_id=task.task_id,
            status=task.status,
            status_message=task.status_message,
            created_at=task.created_at,
            last_updated_at=task.last_updated_at,
            ttl=task.ttl,
            poll_interval=task.poll_interval,
        )

    server: Server[AppContext] = Server(
        "test-tasks-failure",
        lifespan=_make_lifespan(store, task_done_events),
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )
    server.experimental.enable_tasks(on_get_task=handle_get_task)

    async with Client(server) as client:
        # Send task request
        create_result = await client.session.send_request(
            CallToolRequest(
                params=CallToolRequestParams(
                    name="failing_task",
                    arguments={},
                    task=TaskMetadata(ttl=60000),
                ),
            ),
            CreateTaskResult,
        )

        task_id = create_result.task.task_id

        # Wait for task to complete (even though it fails)
        await task_done_events[task_id].wait()

        # Check that task was auto-failed
        task_status = await client.session.experimental.get_task(task_id)

        assert task_status.status == "failed"
        assert task_status.status_message == "Something went wrong!"
