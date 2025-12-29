"""End-to-end integration tests for tasks functionality.

These tests demonstrate the full task lifecycle:
1. Client sends task-augmented request (tools/call with task metadata)
2. Server creates task and returns CreateTaskResult immediately
3. Background work executes (using task_execution context manager)
4. Client polls with tasks/get
5. Client retrieves result with tasks/result
"""

from dataclasses import dataclass, field
from typing import Any

import anyio
import pytest
from anyio import Event
from anyio.abc import TaskGroup

from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.experimental.tasks.helpers import task_execution
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    TASK_REQUIRED,
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    ClientRequest,
    ClientResult,
    CreateTaskResult,
    GetTaskPayloadRequest,
    GetTaskPayloadRequestParams,
    GetTaskPayloadResult,
    GetTaskRequest,
    GetTaskRequestParams,
    GetTaskResult,
    ListTasksRequest,
    ListTasksResult,
    ServerNotification,
    ServerRequest,
    TaskMetadata,
    TextContent,
    Tool,
    ToolExecution,
)


@dataclass
class AppContext:
    """Application context passed via lifespan_context."""

    task_group: TaskGroup
    store: InMemoryTaskStore
    # Events to signal when tasks complete (for testing without sleeps)
    task_done_events: dict[str, Event] = field(default_factory=lambda: {})


@pytest.mark.anyio
async def test_task_lifecycle_with_task_execution() -> None:
    """
    Test the complete task lifecycle using the task_execution pattern.

    This demonstrates the recommended way to implement task-augmented tools:
    1. Create task in store
    2. Spawn work using task_execution() context manager
    3. Return CreateTaskResult immediately
    4. Work executes in background, auto-fails on exception
    """
    # Note: We bypass the normal lifespan mechanism and pass context directly to _handle_message
    server: Server[AppContext, Any] = Server("test-tasks")  # type: ignore[assignment]
    store = InMemoryTaskStore()

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="process_data",
                description="Process data asynchronously",
                inputSchema={
                    "type": "object",
                    "properties": {"input": {"type": "string"}},
                },
                execution=ToolExecution(taskSupport=TASK_REQUIRED),
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent] | CreateTaskResult:
        ctx = server.request_context
        app = ctx.lifespan_context
        if name == "process_data" and ctx.experimental.is_task:
            # 1. Create task in store
            task_metadata = ctx.experimental.task_metadata
            assert task_metadata is not None
            task = await app.store.create_task(task_metadata)

            # 2. Create event to signal completion (for testing)
            done_event = Event()
            app.task_done_events[task.taskId] = done_event

            # 3. Define work function using task_execution for safety
            async def do_work():
                async with task_execution(task.taskId, app.store) as task_ctx:
                    await task_ctx.update_status("Processing input...")
                    # Simulate work
                    input_value = arguments.get("input", "")
                    result_text = f"Processed: {input_value.upper()}"
                    await task_ctx.complete(CallToolResult(content=[TextContent(type="text", text=result_text)]))
                # Signal completion
                done_event.set()

            # 4. Spawn work in task group (from lifespan_context)
            app.task_group.start_soon(do_work)

            # 5. Return CreateTaskResult immediately
            return CreateTaskResult(task=task)

        raise NotImplementedError

    # Register task query handlers (delegate to store)
    @server.experimental.get_task()
    async def handle_get_task(request: GetTaskRequest) -> GetTaskResult:
        app = server.request_context.lifespan_context
        task = await app.store.get_task(request.params.taskId)
        assert task is not None, f"Test setup error: task {request.params.taskId} should exist"
        return GetTaskResult(
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
        request: GetTaskPayloadRequest,
    ) -> GetTaskPayloadResult:
        app = server.request_context.lifespan_context
        result = await app.store.get_result(request.params.taskId)
        assert result is not None, f"Test setup error: result for {request.params.taskId} should exist"
        assert isinstance(result, CallToolResult)
        # Return as GetTaskPayloadResult (which accepts extra fields)
        return GetTaskPayloadResult(**result.model_dump())

    @server.experimental.list_tasks()
    async def handle_list_tasks(request: ListTasksRequest) -> ListTasksResult:
        raise NotImplementedError

    # Set up client-server communication
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def message_handler(
        message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
    ) -> None: ...  # pragma: no cover

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
        # Create app context with task group and store
        app_context = AppContext(task_group=tg, store=store)
        tg.start_soon(run_server, app_context)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            message_handler=message_handler,
        ) as client_session:
            await client_session.initialize()

            # === Step 1: Send task-augmented tool call ===
            create_result = await client_session.send_request(
                ClientRequest(
                    CallToolRequest(
                        params=CallToolRequestParams(
                            name="process_data",
                            arguments={"input": "hello world"},
                            task=TaskMetadata(ttl=60000),
                        ),
                    )
                ),
                CreateTaskResult,
            )

            assert isinstance(create_result, CreateTaskResult)
            assert create_result.task.status == "working"
            task_id = create_result.task.taskId

            # === Step 2: Wait for task to complete ===
            await app_context.task_done_events[task_id].wait()

            task_status = await client_session.send_request(
                ClientRequest(GetTaskRequest(params=GetTaskRequestParams(taskId=task_id))),
                GetTaskResult,
            )

            assert task_status.taskId == task_id
            assert task_status.status == "completed"

            # === Step 3: Retrieve the actual result ===
            task_result = await client_session.send_request(
                ClientRequest(GetTaskPayloadRequest(params=GetTaskPayloadRequestParams(taskId=task_id))),
                CallToolResult,
            )

            assert len(task_result.content) == 1
            content = task_result.content[0]
            assert isinstance(content, TextContent)
            assert content.text == "Processed: HELLO WORLD"

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_task_auto_fails_on_exception() -> None:
    """Test that task_execution automatically fails the task on unhandled exception."""
    # Note: We bypass the normal lifespan mechanism and pass context directly to _handle_message
    server: Server[AppContext, Any] = Server("test-tasks-failure")  # type: ignore[assignment]
    store = InMemoryTaskStore()

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="failing_task",
                description="A task that fails",
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent] | CreateTaskResult:
        ctx = server.request_context
        app = ctx.lifespan_context
        if name == "failing_task" and ctx.experimental.is_task:
            task_metadata = ctx.experimental.task_metadata
            assert task_metadata is not None
            task = await app.store.create_task(task_metadata)

            # Create event to signal completion (for testing)
            done_event = Event()
            app.task_done_events[task.taskId] = done_event

            async def do_failing_work():
                async with task_execution(task.taskId, app.store) as task_ctx:
                    await task_ctx.update_status("About to fail...")
                    raise RuntimeError("Something went wrong!")
                    # Note: complete() is never called, but task_execution
                    # will automatically call fail() due to the exception
                # This line is reached because task_execution suppresses the exception
                done_event.set()

            app.task_group.start_soon(do_failing_work)
            return CreateTaskResult(task=task)

        raise NotImplementedError

    @server.experimental.get_task()
    async def handle_get_task(request: GetTaskRequest) -> GetTaskResult:
        app = server.request_context.lifespan_context
        task = await app.store.get_task(request.params.taskId)
        assert task is not None, f"Test setup error: task {request.params.taskId} should exist"
        return GetTaskResult(
            taskId=task.taskId,
            status=task.status,
            statusMessage=task.statusMessage,
            createdAt=task.createdAt,
            lastUpdatedAt=task.lastUpdatedAt,
            ttl=task.ttl,
            pollInterval=task.pollInterval,
        )

    # Set up streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def message_handler(
        message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
    ) -> None: ...  # pragma: no cover

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

            # Send task request
            create_result = await client_session.send_request(
                ClientRequest(
                    CallToolRequest(
                        params=CallToolRequestParams(
                            name="failing_task",
                            arguments={},
                            task=TaskMetadata(ttl=60000),
                        ),
                    )
                ),
                CreateTaskResult,
            )

            task_id = create_result.task.taskId

            # Wait for task to complete (even though it fails)
            await app_context.task_done_events[task_id].wait()

            # Check that task was auto-failed
            task_status = await client_session.send_request(
                ClientRequest(GetTaskRequest(params=GetTaskRequestParams(taskId=task_id))),
                GetTaskResult,
            )

            assert task_status.status == "failed"
            assert task_status.statusMessage == "Something went wrong!"

            tg.cancel_scope.cancel()
