"""Tests for server-side task support (handlers, capabilities, integration)."""

from datetime import datetime, timezone
from typing import Any

import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    CancelTaskRequest,
    CancelTaskRequestParams,
    CancelTaskResult,
    ClientRequest,
    ClientResult,
    GetTaskPayloadRequest,
    GetTaskPayloadRequestParams,
    GetTaskPayloadResult,
    GetTaskRequest,
    GetTaskRequestParams,
    GetTaskResult,
    ListTasksRequest,
    ListTasksResult,
    ListToolsRequest,
    ListToolsResult,
    ServerNotification,
    ServerRequest,
    ServerResult,
    Task,
    TaskMetadata,
    TextContent,
    Tool,
    ToolExecution,
)

# --- Experimental handler tests ---


@pytest.mark.anyio
async def test_list_tasks_handler() -> None:
    """Test that experimental list_tasks handler works."""
    server = Server("test")

    test_tasks = [
        Task(
            taskId="task-1",
            status="working",
            createdAt=datetime.now(timezone.utc),
            ttl=60000,
            pollInterval=1000,
        ),
        Task(
            taskId="task-2",
            status="completed",
            createdAt=datetime.now(timezone.utc),
            ttl=60000,
            pollInterval=1000,
        ),
    ]

    @server.experimental.list_tasks()
    async def handle_list_tasks(request: ListTasksRequest) -> ListTasksResult:
        return ListTasksResult(tasks=test_tasks)

    handler = server.request_handlers[ListTasksRequest]
    request = ListTasksRequest(method="tasks/list")
    result = await handler(request)

    assert isinstance(result, ServerResult)
    assert isinstance(result.root, ListTasksResult)
    assert len(result.root.tasks) == 2
    assert result.root.tasks[0].taskId == "task-1"
    assert result.root.tasks[1].taskId == "task-2"


@pytest.mark.anyio
async def test_get_task_handler() -> None:
    """Test that experimental get_task handler works."""
    server = Server("test")

    @server.experimental.get_task()
    async def handle_get_task(request: GetTaskRequest) -> GetTaskResult:
        return GetTaskResult(
            taskId=request.params.taskId,
            status="working",
            createdAt=datetime.now(timezone.utc),
            ttl=60000,
            pollInterval=1000,
        )

    handler = server.request_handlers[GetTaskRequest]
    request = GetTaskRequest(
        method="tasks/get",
        params=GetTaskRequestParams(taskId="test-task-123"),
    )
    result = await handler(request)

    assert isinstance(result, ServerResult)
    assert isinstance(result.root, GetTaskResult)
    assert result.root.taskId == "test-task-123"
    assert result.root.status == "working"


@pytest.mark.anyio
async def test_get_task_result_handler() -> None:
    """Test that experimental get_task_result handler works."""
    server = Server("test")

    @server.experimental.get_task_result()
    async def handle_get_task_result(request: GetTaskPayloadRequest) -> GetTaskPayloadResult:
        return GetTaskPayloadResult()

    handler = server.request_handlers[GetTaskPayloadRequest]
    request = GetTaskPayloadRequest(
        method="tasks/result",
        params=GetTaskPayloadRequestParams(taskId="test-task-123"),
    )
    result = await handler(request)

    assert isinstance(result, ServerResult)
    assert isinstance(result.root, GetTaskPayloadResult)


@pytest.mark.anyio
async def test_cancel_task_handler() -> None:
    """Test that experimental cancel_task handler works."""
    server = Server("test")

    @server.experimental.cancel_task()
    async def handle_cancel_task(request: CancelTaskRequest) -> CancelTaskResult:
        return CancelTaskResult(
            taskId=request.params.taskId,
            status="cancelled",
            createdAt=datetime.now(timezone.utc),
            ttl=60000,
        )

    handler = server.request_handlers[CancelTaskRequest]
    request = CancelTaskRequest(
        method="tasks/cancel",
        params=CancelTaskRequestParams(taskId="test-task-123"),
    )
    result = await handler(request)

    assert isinstance(result, ServerResult)
    assert isinstance(result.root, CancelTaskResult)
    assert result.root.taskId == "test-task-123"
    assert result.root.status == "cancelled"


# --- Server capabilities tests ---


@pytest.mark.anyio
async def test_server_capabilities_include_tasks() -> None:
    """Test that server capabilities include tasks when handlers are registered."""
    server = Server("test")

    @server.experimental.list_tasks()
    async def handle_list_tasks(request: ListTasksRequest) -> ListTasksResult:
        return ListTasksResult(tasks=[])

    @server.experimental.cancel_task()
    async def handle_cancel_task(request: CancelTaskRequest) -> CancelTaskResult:
        return CancelTaskResult(
            taskId=request.params.taskId,
            status="cancelled",
            createdAt=datetime.now(timezone.utc),
            ttl=None,
        )

    capabilities = server.get_capabilities(
        notification_options=NotificationOptions(),
        experimental_capabilities={},
    )

    assert capabilities.tasks is not None
    assert capabilities.tasks.list is not None
    assert capabilities.tasks.cancel is not None
    assert capabilities.tasks.requests is not None
    assert capabilities.tasks.requests.tools is not None


@pytest.mark.anyio
async def test_server_capabilities_partial_tasks() -> None:
    """Test capabilities with only some task handlers registered."""
    server = Server("test")

    @server.experimental.list_tasks()
    async def handle_list_tasks(request: ListTasksRequest) -> ListTasksResult:
        return ListTasksResult(tasks=[])

    # Only list_tasks registered, not cancel_task

    capabilities = server.get_capabilities(
        notification_options=NotificationOptions(),
        experimental_capabilities={},
    )

    assert capabilities.tasks is not None
    assert capabilities.tasks.list is not None
    assert capabilities.tasks.cancel is None  # Not registered


# --- Tool annotation tests ---


@pytest.mark.anyio
async def test_tool_with_task_execution_metadata() -> None:
    """Test that tools can declare task execution mode."""
    server = Server("test")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="quick_tool",
                description="Fast tool",
                inputSchema={"type": "object", "properties": {}},
                execution=ToolExecution(task="never"),
            ),
            Tool(
                name="long_tool",
                description="Long running tool",
                inputSchema={"type": "object", "properties": {}},
                execution=ToolExecution(task="always"),
            ),
            Tool(
                name="flexible_tool",
                description="Can be either",
                inputSchema={"type": "object", "properties": {}},
                execution=ToolExecution(task="optional"),
            ),
        ]

    tools_handler = server.request_handlers[ListToolsRequest]
    request = ListToolsRequest(method="tools/list")
    result = await tools_handler(request)

    assert isinstance(result, ServerResult)
    assert isinstance(result.root, ListToolsResult)
    tools = result.root.tools

    assert tools[0].execution is not None
    assert tools[0].execution.task == "never"
    assert tools[1].execution is not None
    assert tools[1].execution.task == "always"
    assert tools[2].execution is not None
    assert tools[2].execution.task == "optional"


# --- Integration tests ---


@pytest.mark.anyio
async def test_task_metadata_in_call_tool_request() -> None:
    """Test that task metadata is accessible via RequestContext when calling a tool."""
    server = Server("test")
    captured_task_metadata: TaskMetadata | None = None

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="long_task",
                description="A long running task",
                inputSchema={"type": "object", "properties": {}},
                execution=ToolExecution(task="optional"),
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        nonlocal captured_task_metadata
        ctx = server.request_context
        captured_task_metadata = ctx.experimental.task_metadata
        return [TextContent(type="text", text="done")]

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def message_handler(
        message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
            raise message

    async def run_server():
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
            async with anyio.create_task_group() as tg:

                async def handle_messages():
                    async for message in server_session.incoming_messages:
                        await server._handle_message(message, server_session, {}, False)

                tg.start_soon(handle_messages)
                await anyio.sleep_forever()

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            message_handler=message_handler,
        ) as client_session:
            await client_session.initialize()

            # Call tool with task metadata
            await client_session.send_request(
                ClientRequest(
                    CallToolRequest(
                        params=CallToolRequestParams(
                            name="long_task",
                            arguments={},
                            task=TaskMetadata(ttl=60000),
                        ),
                    )
                ),
                CallToolResult,
            )

            tg.cancel_scope.cancel()

    assert captured_task_metadata is not None
    assert captured_task_metadata.ttl == 60000


@pytest.mark.anyio
async def test_task_metadata_is_task_property() -> None:
    """Test that RequestContext.experimental.is_task works correctly."""
    server = Server("test")
    is_task_values: list[bool] = []

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="test_tool",
                description="Test tool",
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        ctx = server.request_context
        is_task_values.append(ctx.experimental.is_task)
        return [TextContent(type="text", text="done")]

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def message_handler(
        message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
            raise message

    async def run_server():
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
            async with anyio.create_task_group() as tg:

                async def handle_messages():
                    async for message in server_session.incoming_messages:
                        await server._handle_message(message, server_session, {}, False)

                tg.start_soon(handle_messages)
                await anyio.sleep_forever()

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            message_handler=message_handler,
        ) as client_session:
            await client_session.initialize()

            # Call without task metadata
            await client_session.send_request(
                ClientRequest(
                    CallToolRequest(
                        params=CallToolRequestParams(name="test_tool", arguments={}),
                    )
                ),
                CallToolResult,
            )

            # Call with task metadata
            await client_session.send_request(
                ClientRequest(
                    CallToolRequest(
                        params=CallToolRequestParams(
                            name="test_tool",
                            arguments={},
                            task=TaskMetadata(ttl=60000),
                        ),
                    )
                ),
                CallToolResult,
            )

            tg.cancel_scope.cancel()

    assert len(is_task_values) == 2
    assert is_task_values[0] is False  # First call without task
    assert is_task_values[1] is True  # Second call with task
