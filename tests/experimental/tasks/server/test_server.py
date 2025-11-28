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
from mcp.shared.exceptions import McpError
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.shared.response_router import ResponseRouter
from mcp.shared.session import RequestResponder
from mcp.types import (
    INVALID_REQUEST,
    TASK_FORBIDDEN,
    TASK_OPTIONAL,
    TASK_REQUIRED,
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    CancelTaskRequest,
    CancelTaskRequestParams,
    CancelTaskResult,
    ClientRequest,
    ClientResult,
    ErrorData,
    GetTaskPayloadRequest,
    GetTaskPayloadRequestParams,
    GetTaskPayloadResult,
    GetTaskRequest,
    GetTaskRequestParams,
    GetTaskResult,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCResponse,
    ListTasksRequest,
    ListTasksResult,
    ListToolsRequest,
    ListToolsResult,
    SamplingMessage,
    ServerCapabilities,
    ServerNotification,
    ServerRequest,
    ServerResult,
    Task,
    TaskMetadata,
    TextContent,
    Tool,
    ToolExecution,
)


@pytest.mark.anyio
async def test_list_tasks_handler() -> None:
    """Test that experimental list_tasks handler works."""
    server = Server("test")

    now = datetime.now(timezone.utc)
    test_tasks = [
        Task(
            taskId="task-1",
            status="working",
            createdAt=now,
            lastUpdatedAt=now,
            ttl=60000,
            pollInterval=1000,
        ),
        Task(
            taskId="task-2",
            status="completed",
            createdAt=now,
            lastUpdatedAt=now,
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
        now = datetime.now(timezone.utc)
        return GetTaskResult(
            taskId=request.params.taskId,
            status="working",
            createdAt=now,
            lastUpdatedAt=now,
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
        now = datetime.now(timezone.utc)
        return CancelTaskResult(
            taskId=request.params.taskId,
            status="cancelled",
            createdAt=now,
            lastUpdatedAt=now,
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


@pytest.mark.anyio
async def test_server_capabilities_include_tasks() -> None:
    """Test that server capabilities include tasks when handlers are registered."""
    server = Server("test")

    @server.experimental.list_tasks()
    async def handle_list_tasks(request: ListTasksRequest) -> ListTasksResult:
        raise NotImplementedError

    @server.experimental.cancel_task()
    async def handle_cancel_task(request: CancelTaskRequest) -> CancelTaskResult:
        raise NotImplementedError

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
        raise NotImplementedError

    # Only list_tasks registered, not cancel_task

    capabilities = server.get_capabilities(
        notification_options=NotificationOptions(),
        experimental_capabilities={},
    )

    assert capabilities.tasks is not None
    assert capabilities.tasks.list is not None
    assert capabilities.tasks.cancel is None  # Not registered


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
                execution=ToolExecution(taskSupport=TASK_FORBIDDEN),
            ),
            Tool(
                name="long_tool",
                description="Long running tool",
                inputSchema={"type": "object", "properties": {}},
                execution=ToolExecution(taskSupport=TASK_REQUIRED),
            ),
            Tool(
                name="flexible_tool",
                description="Can be either",
                inputSchema={"type": "object", "properties": {}},
                execution=ToolExecution(taskSupport=TASK_OPTIONAL),
            ),
        ]

    tools_handler = server.request_handlers[ListToolsRequest]
    request = ListToolsRequest(method="tools/list")
    result = await tools_handler(request)

    assert isinstance(result, ServerResult)
    assert isinstance(result.root, ListToolsResult)
    tools = result.root.tools

    assert tools[0].execution is not None
    assert tools[0].execution.taskSupport == TASK_FORBIDDEN
    assert tools[1].execution is not None
    assert tools[1].execution.taskSupport == TASK_REQUIRED
    assert tools[2].execution is not None
    assert tools[2].execution.taskSupport == TASK_OPTIONAL


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
                execution=ToolExecution(taskSupport="optional"),
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
    ) -> None: ...  # pragma: no branch

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
    ) -> None: ...  # pragma: no branch

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


@pytest.mark.anyio
async def test_update_capabilities_no_handlers() -> None:
    """Test that update_capabilities returns early when no task handlers are registered."""
    server = Server("test-no-handlers")
    # Access experimental to initialize it, but don't register any task handlers
    _ = server.experimental

    caps = server.get_capabilities(NotificationOptions(), {})

    # Without any task handlers registered, tasks capability should be None
    assert caps.tasks is None


@pytest.mark.anyio
async def test_default_task_handlers_via_enable_tasks() -> None:
    """Test that enable_tasks() auto-registers working default handlers.

    This exercises the default handlers in lowlevel/experimental.py:
    - _default_get_task (task not found)
    - _default_get_task_result
    - _default_list_tasks
    - _default_cancel_task
    """
    server = Server("test-default-handlers")
    # Enable tasks with default handlers (no custom handlers registered)
    task_support = server.experimental.enable_tasks()
    store = task_support.store

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def message_handler(
        message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
    ) -> None: ...  # pragma: no branch

    async def run_server() -> None:
        async with task_support.run():
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
                task_support.configure_session(server_session)
                async for message in server_session.incoming_messages:
                    await server._handle_message(message, server_session, {}, False)

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            message_handler=message_handler,
        ) as client_session:
            await client_session.initialize()

            # Create a task directly in the store for testing
            task = await store.create_task(TaskMetadata(ttl=60000))

            # Test list_tasks (default handler)
            list_result = await client_session.send_request(
                ClientRequest(ListTasksRequest()),
                ListTasksResult,
            )
            assert len(list_result.tasks) == 1
            assert list_result.tasks[0].taskId == task.taskId

            # Test get_task (default handler - found)
            get_result = await client_session.send_request(
                ClientRequest(GetTaskRequest(params=GetTaskRequestParams(taskId=task.taskId))),
                GetTaskResult,
            )
            assert get_result.taskId == task.taskId
            assert get_result.status == "working"

            # Test get_task (default handler - not found path)
            with pytest.raises(McpError, match="not found"):
                await client_session.send_request(
                    ClientRequest(GetTaskRequest(params=GetTaskRequestParams(taskId="nonexistent-task"))),
                    GetTaskResult,
                )

            # Create a completed task to test get_task_result
            completed_task = await store.create_task(TaskMetadata(ttl=60000))
            await store.store_result(
                completed_task.taskId, CallToolResult(content=[TextContent(type="text", text="Test result")])
            )
            await store.update_task(completed_task.taskId, status="completed")

            # Test get_task_result (default handler)
            payload_result = await client_session.send_request(
                ClientRequest(GetTaskPayloadRequest(params=GetTaskPayloadRequestParams(taskId=completed_task.taskId))),
                GetTaskPayloadResult,
            )
            # The result should have the related-task metadata
            assert payload_result.meta is not None
            assert "io.modelcontextprotocol/related-task" in payload_result.meta

            # Test cancel_task (default handler)
            cancel_result = await client_session.send_request(
                ClientRequest(CancelTaskRequest(params=CancelTaskRequestParams(taskId=task.taskId))),
                CancelTaskResult,
            )
            assert cancel_result.taskId == task.taskId
            assert cancel_result.status == "cancelled"

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_build_elicit_form_request() -> None:
    """Test that _build_elicit_form_request builds a proper elicitation request."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    try:
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(),
            ),
        ) as server_session:
            # Test without task_id
            request = server_session._build_elicit_form_request(
                message="Test message",
                requestedSchema={"type": "object", "properties": {"answer": {"type": "string"}}},
            )
            assert request.method == "elicitation/create"
            assert request.params is not None
            assert request.params["message"] == "Test message"

            # Test with related_task_id (adds related-task metadata)
            request_with_task = server_session._build_elicit_form_request(
                message="Task message",
                requestedSchema={"type": "object"},
                related_task_id="test-task-123",
            )
            assert request_with_task.method == "elicitation/create"
            assert request_with_task.params is not None
            assert "_meta" in request_with_task.params
            assert "io.modelcontextprotocol/related-task" in request_with_task.params["_meta"]
            assert (
                request_with_task.params["_meta"]["io.modelcontextprotocol/related-task"]["taskId"] == "test-task-123"
            )
    finally:  # pragma: no cover
        await server_to_client_send.aclose()
        await server_to_client_receive.aclose()
        await client_to_server_send.aclose()
        await client_to_server_receive.aclose()


@pytest.mark.anyio
async def test_build_elicit_url_request() -> None:
    """Test that _build_elicit_url_request builds a proper URL mode elicitation request."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    try:
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(),
            ),
        ) as server_session:
            # Test without related_task_id
            request = server_session._build_elicit_url_request(
                message="Please authorize with GitHub",
                url="https://github.com/login/oauth/authorize",
                elicitation_id="oauth-123",
            )
            assert request.method == "elicitation/create"
            assert request.params is not None
            assert request.params["message"] == "Please authorize with GitHub"
            assert request.params["url"] == "https://github.com/login/oauth/authorize"
            assert request.params["elicitationId"] == "oauth-123"
            assert request.params["mode"] == "url"

            # Test with related_task_id (adds related-task metadata)
            request_with_task = server_session._build_elicit_url_request(
                message="OAuth required",
                url="https://example.com/oauth",
                elicitation_id="oauth-456",
                related_task_id="test-task-789",
            )
            assert request_with_task.method == "elicitation/create"
            assert request_with_task.params is not None
            assert "_meta" in request_with_task.params
            assert "io.modelcontextprotocol/related-task" in request_with_task.params["_meta"]
            assert (
                request_with_task.params["_meta"]["io.modelcontextprotocol/related-task"]["taskId"] == "test-task-789"
            )
    finally:  # pragma: no cover
        await server_to_client_send.aclose()
        await server_to_client_receive.aclose()
        await client_to_server_send.aclose()
        await client_to_server_receive.aclose()


@pytest.mark.anyio
async def test_build_create_message_request() -> None:
    """Test that _build_create_message_request builds a proper sampling request."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    try:
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(),
            ),
        ) as server_session:
            messages = [
                SamplingMessage(role="user", content=TextContent(type="text", text="Hello")),
            ]

            # Test without task_id
            request = server_session._build_create_message_request(
                messages=messages,
                max_tokens=100,
                system_prompt="You are helpful",
            )
            assert request.method == "sampling/createMessage"
            assert request.params is not None
            assert request.params["maxTokens"] == 100

            # Test with related_task_id (adds related-task metadata)
            request_with_task = server_session._build_create_message_request(
                messages=messages,
                max_tokens=50,
                related_task_id="sampling-task-456",
            )
            assert request_with_task.method == "sampling/createMessage"
            assert request_with_task.params is not None
            assert "_meta" in request_with_task.params
            assert "io.modelcontextprotocol/related-task" in request_with_task.params["_meta"]
            assert (
                request_with_task.params["_meta"]["io.modelcontextprotocol/related-task"]["taskId"]
                == "sampling-task-456"
            )
    finally:  # pragma: no cover
        await server_to_client_send.aclose()
        await server_to_client_receive.aclose()
        await client_to_server_send.aclose()
        await client_to_server_receive.aclose()


@pytest.mark.anyio
async def test_send_message() -> None:
    """Test that send_message sends a raw session message."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    try:
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(),
            ),
        ) as server_session:
            # Create a test message
            notification = JSONRPCNotification(jsonrpc="2.0", method="test/notification")
            message = SessionMessage(
                message=JSONRPCMessage(notification),
                metadata=ServerMessageMetadata(related_request_id="test-req-1"),
            )

            # Send the message
            await server_session.send_message(message)

            # Verify it was sent to the stream
            received = await server_to_client_receive.receive()
            assert isinstance(received.message.root, JSONRPCNotification)
            assert received.message.root.method == "test/notification"
    finally:  # pragma: no cover
        await server_to_client_send.aclose()
        await server_to_client_receive.aclose()
        await client_to_server_send.aclose()
        await client_to_server_receive.aclose()


@pytest.mark.anyio
async def test_response_routing_success() -> None:
    """Test that response routing works for success responses."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    # Track routed responses with event for synchronization
    routed_responses: list[dict[str, Any]] = []
    response_received = anyio.Event()

    class TestRouter(ResponseRouter):
        def route_response(self, request_id: str | int, response: dict[str, Any]) -> bool:
            routed_responses.append({"id": request_id, "response": response})
            response_received.set()
            return True  # Handled

        def route_error(self, request_id: str | int, error: ErrorData) -> bool:
            raise NotImplementedError

    try:
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(),
            ),
        ) as server_session:
            router = TestRouter()
            server_session.add_response_router(router)

            # Simulate receiving a response from client
            response = JSONRPCResponse(jsonrpc="2.0", id="test-req-1", result={"status": "ok"})
            message = SessionMessage(message=JSONRPCMessage(response))

            # Send from "client" side
            await client_to_server_send.send(message)

            # Wait for response to be routed
            with anyio.fail_after(5):
                await response_received.wait()

            # Verify response was routed
            assert len(routed_responses) == 1
            assert routed_responses[0]["id"] == "test-req-1"
            assert routed_responses[0]["response"]["status"] == "ok"
    finally:  # pragma: no cover
        await server_to_client_send.aclose()
        await server_to_client_receive.aclose()
        await client_to_server_send.aclose()
        await client_to_server_receive.aclose()


@pytest.mark.anyio
async def test_response_routing_error() -> None:
    """Test that error routing works for error responses."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    # Track routed errors with event for synchronization
    routed_errors: list[dict[str, Any]] = []
    error_received = anyio.Event()

    class TestRouter(ResponseRouter):
        def route_response(self, request_id: str | int, response: dict[str, Any]) -> bool:
            raise NotImplementedError

        def route_error(self, request_id: str | int, error: ErrorData) -> bool:
            routed_errors.append({"id": request_id, "error": error})
            error_received.set()
            return True  # Handled

    try:
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(),
            ),
        ) as server_session:
            router = TestRouter()
            server_session.add_response_router(router)

            # Simulate receiving an error response from client
            error_data = ErrorData(code=INVALID_REQUEST, message="Test error")
            error_response = JSONRPCError(jsonrpc="2.0", id="test-req-2", error=error_data)
            message = SessionMessage(message=JSONRPCMessage(error_response))

            # Send from "client" side
            await client_to_server_send.send(message)

            # Wait for error to be routed
            with anyio.fail_after(5):
                await error_received.wait()

            # Verify error was routed
            assert len(routed_errors) == 1
            assert routed_errors[0]["id"] == "test-req-2"
            assert routed_errors[0]["error"].message == "Test error"
    finally:  # pragma: no cover
        await server_to_client_send.aclose()
        await server_to_client_receive.aclose()
        await client_to_server_send.aclose()
        await client_to_server_receive.aclose()


@pytest.mark.anyio
async def test_response_routing_skips_non_matching_routers() -> None:
    """Test that routing continues to next router when first doesn't match."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    # Track which routers were called
    router_calls: list[str] = []
    response_received = anyio.Event()

    class NonMatchingRouter(ResponseRouter):
        def route_response(self, request_id: str | int, response: dict[str, Any]) -> bool:
            router_calls.append("non_matching_response")
            return False  # Doesn't handle it

        def route_error(self, request_id: str | int, error: ErrorData) -> bool:
            raise NotImplementedError

    class MatchingRouter(ResponseRouter):
        def route_response(self, request_id: str | int, response: dict[str, Any]) -> bool:
            router_calls.append("matching_response")
            response_received.set()
            return True  # Handles it

        def route_error(self, request_id: str | int, error: ErrorData) -> bool:
            raise NotImplementedError

    try:
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(),
            ),
        ) as server_session:
            # Add non-matching router first, then matching router
            server_session.add_response_router(NonMatchingRouter())
            server_session.add_response_router(MatchingRouter())

            # Send a response - should skip first router and be handled by second
            response = JSONRPCResponse(jsonrpc="2.0", id="test-req-1", result={"status": "ok"})
            message = SessionMessage(message=JSONRPCMessage(response))
            await client_to_server_send.send(message)

            with anyio.fail_after(5):
                await response_received.wait()

            # Verify both routers were called (first returned False, second returned True)
            assert router_calls == ["non_matching_response", "matching_response"]
    finally:  # pragma: no cover
        await server_to_client_send.aclose()
        await server_to_client_receive.aclose()
        await client_to_server_send.aclose()
        await client_to_server_receive.aclose()


@pytest.mark.anyio
async def test_error_routing_skips_non_matching_routers() -> None:
    """Test that error routing continues to next router when first doesn't match."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    # Track which routers were called
    router_calls: list[str] = []
    error_received = anyio.Event()

    class NonMatchingRouter(ResponseRouter):
        def route_response(self, request_id: str | int, response: dict[str, Any]) -> bool:
            raise NotImplementedError

        def route_error(self, request_id: str | int, error: ErrorData) -> bool:
            router_calls.append("non_matching_error")
            return False  # Doesn't handle it

    class MatchingRouter(ResponseRouter):
        def route_response(self, request_id: str | int, response: dict[str, Any]) -> bool:
            raise NotImplementedError

        def route_error(self, request_id: str | int, error: ErrorData) -> bool:
            router_calls.append("matching_error")
            error_received.set()
            return True  # Handles it

    try:
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(),
            ),
        ) as server_session:
            # Add non-matching router first, then matching router
            server_session.add_response_router(NonMatchingRouter())
            server_session.add_response_router(MatchingRouter())

            # Send an error - should skip first router and be handled by second
            error_data = ErrorData(code=INVALID_REQUEST, message="Test error")
            error_response = JSONRPCError(jsonrpc="2.0", id="test-req-2", error=error_data)
            message = SessionMessage(message=JSONRPCMessage(error_response))
            await client_to_server_send.send(message)

            with anyio.fail_after(5):
                await error_received.wait()

            # Verify both routers were called (first returned False, second returned True)
            assert router_calls == ["non_matching_error", "matching_error"]
    finally:  # pragma: no cover
        await server_to_client_send.aclose()
        await server_to_client_receive.aclose()
        await client_to_server_send.aclose()
        await client_to_server_receive.aclose()
