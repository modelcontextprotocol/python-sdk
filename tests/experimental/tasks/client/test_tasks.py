"""Tests for the experimental client task methods (session.experimental)."""

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
    CancelTaskRequestParams,
    CancelTaskResult,
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


async def _handle_list_tools(
    ctx: ServerRequestContext[AppContext], params: PaginatedRequestParams | None
) -> ListToolsResult:
    raise NotImplementedError


async def _handle_call_tool_with_done_event(
    ctx: ServerRequestContext[AppContext], params: CallToolRequestParams, *, result_text: str = "Done"
) -> CallToolResult | CreateTaskResult:
    app = ctx.session_lifespan_context
    if ctx.experimental.is_task:
        task_metadata = ctx.experimental.task_metadata
        assert task_metadata is not None
        task = await app.store.create_task(task_metadata)

        done_event = Event()
        app.task_done_events[task.task_id] = done_event

        async def do_work() -> None:
            async with task_execution(task.task_id, app.store) as task_ctx:
                await task_ctx.complete(CallToolResult(content=[TextContent(type="text", text=result_text)]))
            done_event.set()

        app.task_group.start_soon(do_work)
        return CreateTaskResult(task=task)

    raise NotImplementedError


def _make_lifespan(store: InMemoryTaskStore, task_done_events: dict[str, Event]):
    @asynccontextmanager
    async def app_lifespan(server: Server[AppContext]) -> AsyncIterator[AppContext]:
        async with anyio.create_task_group() as tg:
            yield AppContext(task_group=tg, store=store, task_done_events=task_done_events)

    return app_lifespan


async def test_session_experimental_get_task() -> None:
    """Test session.experimental.get_task() method."""
    store = InMemoryTaskStore()
    task_done_events: dict[str, Event] = {}

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
        "test-server",
        session_lifespan=_make_lifespan(store, task_done_events),
        on_list_tools=_handle_list_tools,
        on_call_tool=_handle_call_tool_with_done_event,
    )
    server.experimental.enable_tasks(on_get_task=handle_get_task)

    async with Client(server) as client:
        # Create a task
        create_result = await client.session.send_request(
            CallToolRequest(
                params=CallToolRequestParams(
                    name="test_tool",
                    arguments={},
                    task=TaskMetadata(ttl=60000),
                )
            ),
            CreateTaskResult,
        )
        task_id = create_result.task.task_id

        # Wait for task to complete
        await task_done_events[task_id].wait()

        # Use session.experimental to get task status
        task_status = await client.session.experimental.get_task(task_id)

        assert task_status.task_id == task_id
        assert task_status.status == "completed"


async def test_session_experimental_get_task_result() -> None:
    """Test session.experimental.get_task_result() method."""
    store = InMemoryTaskStore()
    task_done_events: dict[str, Event] = {}

    async def handle_call_tool(
        ctx: ServerRequestContext[AppContext], params: CallToolRequestParams
    ) -> CallToolResult | CreateTaskResult:
        return await _handle_call_tool_with_done_event(ctx, params, result_text="Task result content")

    async def handle_get_task_result(
        ctx: ServerRequestContext[AppContext], params: GetTaskPayloadRequestParams
    ) -> GetTaskPayloadResult:
        app = ctx.session_lifespan_context
        result = await app.store.get_result(params.task_id)
        assert result is not None, f"Test setup error: result for {params.task_id} should exist"
        assert isinstance(result, CallToolResult)
        return GetTaskPayloadResult(**result.model_dump())

    server: Server[AppContext] = Server(
        "test-server",
        session_lifespan=_make_lifespan(store, task_done_events),
        on_list_tools=_handle_list_tools,
        on_call_tool=handle_call_tool,
    )
    server.experimental.enable_tasks(on_task_result=handle_get_task_result)

    async with Client(server) as client:
        # Create a task
        create_result = await client.session.send_request(
            CallToolRequest(
                params=CallToolRequestParams(
                    name="test_tool",
                    arguments={},
                    task=TaskMetadata(ttl=60000),
                )
            ),
            CreateTaskResult,
        )
        task_id = create_result.task.task_id

        # Wait for task to complete
        await task_done_events[task_id].wait()

        # Use TaskClient to get task result
        task_result = await client.session.experimental.get_task_result(task_id, CallToolResult)

        assert len(task_result.content) == 1
        content = task_result.content[0]
        assert isinstance(content, TextContent)
        assert content.text == "Task result content"


async def test_session_experimental_list_tasks() -> None:
    """Test TaskClient.list_tasks() method."""
    store = InMemoryTaskStore()
    task_done_events: dict[str, Event] = {}

    async def handle_list_tasks(
        ctx: ServerRequestContext[AppContext], params: PaginatedRequestParams | None
    ) -> ListTasksResult:
        app = ctx.session_lifespan_context
        cursor = params.cursor if params else None
        tasks_list, next_cursor = await app.store.list_tasks(cursor=cursor)
        return ListTasksResult(tasks=tasks_list, next_cursor=next_cursor)

    server: Server[AppContext] = Server(
        "test-server",
        session_lifespan=_make_lifespan(store, task_done_events),
        on_list_tools=_handle_list_tools,
        on_call_tool=_handle_call_tool_with_done_event,
    )
    server.experimental.enable_tasks(on_list_tasks=handle_list_tasks)

    async with Client(server) as client:
        # Create two tasks
        for _ in range(2):
            create_result = await client.session.send_request(
                CallToolRequest(
                    params=CallToolRequestParams(
                        name="test_tool",
                        arguments={},
                        task=TaskMetadata(ttl=60000),
                    )
                ),
                CreateTaskResult,
            )
            await task_done_events[create_result.task.task_id].wait()

        # Use TaskClient to list tasks
        list_result = await client.session.experimental.list_tasks()

        assert len(list_result.tasks) == 2


async def test_session_experimental_cancel_task() -> None:
    """Test TaskClient.cancel_task() method."""
    store = InMemoryTaskStore()
    task_done_events: dict[str, Event] = {}

    async def handle_call_tool_no_work(
        ctx: ServerRequestContext[AppContext], params: CallToolRequestParams
    ) -> CallToolResult | CreateTaskResult:
        app = ctx.session_lifespan_context
        if ctx.experimental.is_task:
            task_metadata = ctx.experimental.task_metadata
            assert task_metadata is not None
            task = await app.store.create_task(task_metadata)
            # Don't start any work - task stays in "working" status
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

    async def handle_cancel_task(
        ctx: ServerRequestContext[AppContext], params: CancelTaskRequestParams
    ) -> CancelTaskResult:
        app = ctx.session_lifespan_context
        task = await app.store.get_task(params.task_id)
        assert task is not None, f"Test setup error: task {params.task_id} should exist"
        await app.store.update_task(params.task_id, status="cancelled")
        updated_task = await app.store.get_task(params.task_id)
        assert updated_task is not None
        return CancelTaskResult(
            task_id=updated_task.task_id,
            status=updated_task.status,
            created_at=updated_task.created_at,
            last_updated_at=updated_task.last_updated_at,
            ttl=updated_task.ttl,
        )

    server: Server[AppContext] = Server(
        "test-server",
        session_lifespan=_make_lifespan(store, task_done_events),
        on_list_tools=_handle_list_tools,
        on_call_tool=handle_call_tool_no_work,
    )
    server.experimental.enable_tasks(on_get_task=handle_get_task, on_cancel_task=handle_cancel_task)

    async with Client(server) as client:
        # Create a task (but don't complete it)
        create_result = await client.session.send_request(
            CallToolRequest(
                params=CallToolRequestParams(
                    name="test_tool",
                    arguments={},
                    task=TaskMetadata(ttl=60000),
                )
            ),
            CreateTaskResult,
        )
        task_id = create_result.task.task_id

        # Verify task is working
        status_before = await client.session.experimental.get_task(task_id)
        assert status_before.status == "working"

        # Cancel the task
        await client.session.experimental.cancel_task(task_id)

        # Verify task is cancelled
        status_after = await client.session.experimental.get_task(task_id)
        assert status_after.status == "cancelled"
