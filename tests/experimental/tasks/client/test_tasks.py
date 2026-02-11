"""Tests for the experimental client task methods (session.experimental)."""

from dataclasses import dataclass, field
from typing import Any

import anyio
import pytest
from anyio import Event
from anyio.abc import TaskGroup

from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.experimental.tasks.helpers import task_execution
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    CancelTaskRequestParams,
    CancelTaskResult,
    ClientResult,
    CreateTaskResult,
    GetTaskPayloadRequestParams,
    GetTaskPayloadResult,
    GetTaskRequestParams,
    GetTaskResult,
    ListTasksResult,
    ListToolsResult,
    PaginatedRequestParams,
    ServerNotification,
    ServerRequest,
    TaskMetadata,
    TextContent,
    Tool,
)


@dataclass
class AppContext:
    """Application context passed via lifespan_context."""

    task_group: TaskGroup
    store: InMemoryTaskStore
    task_done_events: dict[str, Event] = field(default_factory=lambda: {})


@pytest.mark.anyio
async def test_session_experimental_get_task() -> None:
    """Test session.experimental.get_task() method."""
    # Note: We bypass the normal lifespan mechanism
    store = InMemoryTaskStore()

    async def on_list_tools(ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="test_tool", description="Test", input_schema={"type": "object"})])

    async def on_call_tool(
        ctx: ServerRequestContext[Any], params: CallToolRequestParams
    ) -> CallToolResult | CreateTaskResult:
        app: AppContext = ctx.lifespan_context
        if ctx.experimental.is_task:
            task_metadata = ctx.experimental.task_metadata
            assert task_metadata is not None
            task = await app.store.create_task(task_metadata)

            done_event = Event()
            app.task_done_events[task.task_id] = done_event

            async def do_work():
                async with task_execution(task.task_id, app.store) as task_ctx:
                    await task_ctx.complete(CallToolResult(content=[TextContent(type="text", text="Done")]))
                done_event.set()

            app.task_group.start_soon(do_work)
            return CreateTaskResult(task=task)

        raise NotImplementedError

    async def on_get_task(ctx: ServerRequestContext[Any], params: GetTaskRequestParams) -> GetTaskResult:
        app: AppContext = ctx.lifespan_context
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

    server: Server[AppContext] = Server(  # type: ignore[assignment]
        "test-server",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
    server.experimental.enable_tasks(on_get_task=on_get_task)

    # Set up streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def message_handler(
        message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
    ) -> None: ...  # pragma: no branch

    async def run_server(app_context: AppContext):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        ) as server_session:
            async for message in server_session.incoming_messages:
                await server._handle_message(message, server_session, app_context, raise_exceptions=False)

    async with anyio.create_task_group() as tg:
        app_context = AppContext(task_group=tg, store=store)
        tg.start_soon(run_server, app_context)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            message_handler=message_handler,
        ) as client_session:
            await client_session.initialize()

            # Create a task
            create_result = await client_session.send_request(
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
            await app_context.task_done_events[task_id].wait()

            # Use session.experimental to get task status
            task_status = await client_session.experimental.get_task(task_id)

            assert task_status.task_id == task_id
            assert task_status.status == "completed"

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_session_experimental_get_task_result() -> None:
    """Test session.experimental.get_task_result() method."""
    store = InMemoryTaskStore()

    async def on_list_tools(ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="test_tool", description="Test", input_schema={"type": "object"})])

    async def on_call_tool(
        ctx: ServerRequestContext[Any], params: CallToolRequestParams
    ) -> CallToolResult | CreateTaskResult:
        app: AppContext = ctx.lifespan_context
        if ctx.experimental.is_task:
            task_metadata = ctx.experimental.task_metadata
            assert task_metadata is not None
            task = await app.store.create_task(task_metadata)

            done_event = Event()
            app.task_done_events[task.task_id] = done_event

            async def do_work():
                async with task_execution(task.task_id, app.store) as task_ctx:
                    await task_ctx.complete(
                        CallToolResult(content=[TextContent(type="text", text="Task result content")])
                    )
                done_event.set()

            app.task_group.start_soon(do_work)
            return CreateTaskResult(task=task)

        raise NotImplementedError

    async def on_task_result(
        ctx: ServerRequestContext[Any], params: GetTaskPayloadRequestParams
    ) -> GetTaskPayloadResult:
        app: AppContext = ctx.lifespan_context
        result = await app.store.get_result(params.task_id)
        assert result is not None, f"Test setup error: result for {params.task_id} should exist"
        assert isinstance(result, CallToolResult)
        return GetTaskPayloadResult(**result.model_dump())

    server: Server[AppContext] = Server(  # type: ignore[assignment]
        "test-server",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
    server.experimental.enable_tasks(on_task_result=on_task_result)

    # Set up streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def message_handler(
        message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
    ) -> None: ...  # pragma: no branch

    async def run_server(app_context: AppContext):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        ) as server_session:
            async for message in server_session.incoming_messages:
                await server._handle_message(message, server_session, app_context, raise_exceptions=False)

    async with anyio.create_task_group() as tg:
        app_context = AppContext(task_group=tg, store=store)
        tg.start_soon(run_server, app_context)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            message_handler=message_handler,
        ) as client_session:
            await client_session.initialize()

            # Create a task
            create_result = await client_session.send_request(
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
            await app_context.task_done_events[task_id].wait()

            # Use TaskClient to get task result
            task_result = await client_session.experimental.get_task_result(task_id, CallToolResult)

            assert len(task_result.content) == 1
            content = task_result.content[0]
            assert isinstance(content, TextContent)
            assert content.text == "Task result content"

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_session_experimental_list_tasks() -> None:
    """Test TaskClient.list_tasks() method."""
    store = InMemoryTaskStore()

    async def on_list_tools(ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="test_tool", description="Test", input_schema={"type": "object"})])

    async def on_call_tool(
        ctx: ServerRequestContext[Any], params: CallToolRequestParams
    ) -> CallToolResult | CreateTaskResult:
        app: AppContext = ctx.lifespan_context
        if ctx.experimental.is_task:
            task_metadata = ctx.experimental.task_metadata
            assert task_metadata is not None
            task = await app.store.create_task(task_metadata)

            done_event = Event()
            app.task_done_events[task.task_id] = done_event

            async def do_work():
                async with task_execution(task.task_id, app.store) as task_ctx:
                    await task_ctx.complete(CallToolResult(content=[TextContent(type="text", text="Done")]))
                done_event.set()

            app.task_group.start_soon(do_work)
            return CreateTaskResult(task=task)

        raise NotImplementedError

    async def on_list_tasks(ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None) -> ListTasksResult:
        app: AppContext = ctx.lifespan_context
        tasks_list, next_cursor = await app.store.list_tasks(cursor=params.cursor if params else None)
        return ListTasksResult(tasks=tasks_list, next_cursor=next_cursor)

    server: Server[AppContext] = Server(  # type: ignore[assignment]
        "test-server",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
    server.experimental.enable_tasks(on_list_tasks=on_list_tasks)

    # Set up streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def message_handler(
        message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
    ) -> None: ...  # pragma: no branch

    async def run_server(app_context: AppContext):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        ) as server_session:
            async for message in server_session.incoming_messages:
                await server._handle_message(message, server_session, app_context, raise_exceptions=False)

    async with anyio.create_task_group() as tg:
        app_context = AppContext(task_group=tg, store=store)
        tg.start_soon(run_server, app_context)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            message_handler=message_handler,
        ) as client_session:
            await client_session.initialize()

            # Create two tasks
            for _ in range(2):
                create_result = await client_session.send_request(
                    CallToolRequest(
                        params=CallToolRequestParams(
                            name="test_tool",
                            arguments={},
                            task=TaskMetadata(ttl=60000),
                        )
                    ),
                    CreateTaskResult,
                )
                await app_context.task_done_events[create_result.task.task_id].wait()

            # Use TaskClient to list tasks
            list_result = await client_session.experimental.list_tasks()

            assert len(list_result.tasks) == 2

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_session_experimental_cancel_task() -> None:
    """Test TaskClient.cancel_task() method."""
    store = InMemoryTaskStore()

    async def on_list_tools(ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="test_tool", description="Test", input_schema={"type": "object"})])

    async def on_call_tool(
        ctx: ServerRequestContext[Any], params: CallToolRequestParams
    ) -> CallToolResult | CreateTaskResult:
        app: AppContext = ctx.lifespan_context
        if ctx.experimental.is_task:
            task_metadata = ctx.experimental.task_metadata
            assert task_metadata is not None
            task = await app.store.create_task(task_metadata)
            # Don't start any work - task stays in "working" status
            return CreateTaskResult(task=task)

        raise NotImplementedError

    async def on_get_task(ctx: ServerRequestContext[Any], params: GetTaskRequestParams) -> GetTaskResult:
        app: AppContext = ctx.lifespan_context
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

    async def on_cancel_task(ctx: ServerRequestContext[Any], params: CancelTaskRequestParams) -> CancelTaskResult:
        app: AppContext = ctx.lifespan_context
        task = await app.store.get_task(params.task_id)
        assert task is not None, f"Test setup error: task {params.task_id} should exist"
        await app.store.update_task(params.task_id, status="cancelled")
        # CancelTaskResult extends Task, so we need to return the updated task info
        updated_task = await app.store.get_task(params.task_id)
        assert updated_task is not None
        return CancelTaskResult(
            task_id=updated_task.task_id,
            status=updated_task.status,
            created_at=updated_task.created_at,
            last_updated_at=updated_task.last_updated_at,
            ttl=updated_task.ttl,
        )

    server: Server[AppContext] = Server(  # type: ignore[assignment]
        "test-server",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
    server.experimental.enable_tasks(on_get_task=on_get_task, on_cancel_task=on_cancel_task)

    # Set up streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def message_handler(
        message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
    ) -> None: ...  # pragma: no branch

    async def run_server(app_context: AppContext):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        ) as server_session:
            async for message in server_session.incoming_messages:
                await server._handle_message(message, server_session, app_context, raise_exceptions=False)

    async with anyio.create_task_group() as tg:
        app_context = AppContext(task_group=tg, store=store)
        tg.start_soon(run_server, app_context)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            message_handler=message_handler,
        ) as client_session:
            await client_session.initialize()

            # Create a task (but don't complete it)
            create_result = await client_session.send_request(
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
            status_before = await client_session.experimental.get_task(task_id)
            assert status_before.status == "working"

            # Cancel the task
            await client_session.experimental.cancel_task(task_id)

            # Verify task is cancelled
            status_after = await client_session.experimental.get_task(task_id)
            assert status_after.status == "cancelled"

            tg.cancel_scope.cancel()
