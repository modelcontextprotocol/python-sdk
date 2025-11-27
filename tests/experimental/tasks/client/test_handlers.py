"""Tests for client-side task management handlers (server -> client requests).

These tests verify that clients can handle task-related requests from servers:
- GetTaskRequest - server polling client's task status
- GetTaskPayloadRequest - server getting result from client's task
- ListTasksRequest - server listing client's tasks
- CancelTaskRequest - server cancelling client's task

This is the inverse of the existing tests in test_tasks.py, which test
client -> server task requests.
"""

from dataclasses import dataclass, field

import anyio
import pytest
from anyio import Event
from anyio.abc import TaskGroup

import mcp.types as types
from mcp.client.experimental.task_handlers import ExperimentalTaskHandlers
from mcp.client.session import ClientSession
from mcp.shared.context import RequestContext
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    CancelTaskRequestParams,
    CancelTaskResult,
    ClientResult,
    CreateMessageRequestParams,
    CreateMessageResult,
    CreateTaskResult,
    ErrorData,
    GetTaskPayloadRequestParams,
    GetTaskPayloadResult,
    GetTaskRequestParams,
    GetTaskResult,
    ListTasksResult,
    ServerNotification,
    ServerRequest,
    TaskMetadata,
    TextContent,
)


@dataclass
class ClientTaskContext:
    """Context for managing client-side tasks during tests."""

    task_group: TaskGroup
    store: InMemoryTaskStore
    task_done_events: dict[str, Event] = field(default_factory=lambda: {})


@pytest.mark.anyio
async def test_client_handles_get_task_request() -> None:
    """Test that client can respond to GetTaskRequest from server."""
    with anyio.fail_after(10):  # 10 second timeout
        store = InMemoryTaskStore()

        # Track requests received by client
        received_task_id: str | None = None

        async def get_task_handler(
            context: RequestContext[ClientSession, None],
            params: GetTaskRequestParams,
        ) -> GetTaskResult | ErrorData:
            nonlocal received_task_id
            received_task_id = params.taskId
            task = await store.get_task(params.taskId)
            if task is None:
                return ErrorData(code=types.INVALID_REQUEST, message=f"Task {params.taskId} not found")
            return GetTaskResult(
                taskId=task.taskId,
                status=task.status,
                statusMessage=task.statusMessage,
                createdAt=task.createdAt,
                lastUpdatedAt=task.lastUpdatedAt,
                ttl=task.ttl,
                pollInterval=task.pollInterval,
            )

        # Create streams for bidirectional communication
        server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
        client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

        # Pre-create a task in the store
        await store.create_task(TaskMetadata(ttl=60000), task_id="test-task-123")

        async def message_handler(
            message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
        ) -> None:
            if isinstance(message, Exception):
                raise message

        task_handlers = ExperimentalTaskHandlers(get_task=get_task_handler)
        client_ready = anyio.Event()

        try:
            async with anyio.create_task_group() as tg:

                async def run_client():
                    async with ClientSession(
                        server_to_client_receive,
                        client_to_server_send,
                        message_handler=message_handler,
                        experimental_task_handlers=task_handlers,
                    ):
                        client_ready.set()
                        await anyio.sleep_forever()

                tg.start_soon(run_client)
                await client_ready.wait()

                # Server sends GetTaskRequest to client
                request_id = "req-1"
                request = types.JSONRPCRequest(
                    jsonrpc="2.0",
                    id=request_id,
                    method="tasks/get",
                    params={"taskId": "test-task-123"},
                )
                await server_to_client_send.send(SessionMessage(types.JSONRPCMessage(request)))

                # Server receives response
                response_msg = await client_to_server_receive.receive()
                response = response_msg.message.root
                assert isinstance(response, types.JSONRPCResponse)
                assert response.id == request_id

                # Verify response contains task info
                result = GetTaskResult.model_validate(response.result)
                assert result.taskId == "test-task-123"
                assert result.status == "working"

                # Verify handler was called with correct params
                assert received_task_id == "test-task-123"

                tg.cancel_scope.cancel()
        finally:
            # Properly close all streams
            await server_to_client_send.aclose()
            await server_to_client_receive.aclose()
            await client_to_server_send.aclose()
            await client_to_server_receive.aclose()
            store.cleanup()


@pytest.mark.anyio
async def test_client_handles_get_task_result_request() -> None:
    """Test that client can respond to GetTaskPayloadRequest from server."""
    with anyio.fail_after(10):  # 10 second timeout
        store = InMemoryTaskStore()

        async def get_task_result_handler(
            context: RequestContext[ClientSession, None],
            params: GetTaskPayloadRequestParams,
        ) -> GetTaskPayloadResult | ErrorData:
            result = await store.get_result(params.taskId)
            if result is None:
                return ErrorData(code=types.INVALID_REQUEST, message=f"Result for {params.taskId} not found")
            # Cast to expected type
            assert isinstance(result, types.CallToolResult)
            return GetTaskPayloadResult(**result.model_dump())

        # Set up streams
        server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
        client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

        # Pre-create a completed task
        await store.create_task(TaskMetadata(ttl=60000), task_id="test-task-456")
        await store.store_result(
            "test-task-456",
            types.CallToolResult(content=[TextContent(type="text", text="Task completed successfully!")]),
        )
        await store.update_task("test-task-456", status="completed")

        async def message_handler(
            message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
        ) -> None:
            if isinstance(message, Exception):
                raise message

        task_handlers = ExperimentalTaskHandlers(get_task_result=get_task_result_handler)
        client_ready = anyio.Event()

        try:
            async with anyio.create_task_group() as tg:

                async def run_client():
                    async with ClientSession(
                        server_to_client_receive,
                        client_to_server_send,
                        message_handler=message_handler,
                        experimental_task_handlers=task_handlers,
                    ):
                        client_ready.set()
                        await anyio.sleep_forever()

                tg.start_soon(run_client)
                await client_ready.wait()

                # Server sends GetTaskPayloadRequest to client
                request_id = "req-2"
                request = types.JSONRPCRequest(
                    jsonrpc="2.0",
                    id=request_id,
                    method="tasks/result",
                    params={"taskId": "test-task-456"},
                )
                await server_to_client_send.send(SessionMessage(types.JSONRPCMessage(request)))

                # Receive response
                response_msg = await client_to_server_receive.receive()
                response = response_msg.message.root
                assert isinstance(response, types.JSONRPCResponse)

                # Verify response contains the result
                # GetTaskPayloadResult is a passthrough - access raw dict
                assert isinstance(response.result, dict)
                result_dict = response.result
                assert "content" in result_dict
                assert len(result_dict["content"]) == 1
                content_item = result_dict["content"][0]
                assert content_item["type"] == "text"
                assert content_item["text"] == "Task completed successfully!"

                tg.cancel_scope.cancel()
        finally:
            await server_to_client_send.aclose()
            await server_to_client_receive.aclose()
            await client_to_server_send.aclose()
            await client_to_server_receive.aclose()
            store.cleanup()


@pytest.mark.anyio
async def test_client_handles_list_tasks_request() -> None:
    """Test that client can respond to ListTasksRequest from server."""
    with anyio.fail_after(10):  # 10 second timeout
        store = InMemoryTaskStore()

        async def list_tasks_handler(
            context: RequestContext[ClientSession, None],
            params: types.PaginatedRequestParams | None,
        ) -> ListTasksResult | ErrorData:
            cursor = params.cursor if params else None
            tasks_list, next_cursor = await store.list_tasks(cursor=cursor)
            return ListTasksResult(tasks=tasks_list, nextCursor=next_cursor)

        # Set up streams
        server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
        client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

        # Pre-create some tasks
        await store.create_task(TaskMetadata(ttl=60000), task_id="task-1")
        await store.create_task(TaskMetadata(ttl=60000), task_id="task-2")

        async def message_handler(
            message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
        ) -> None:
            if isinstance(message, Exception):
                raise message

        task_handlers = ExperimentalTaskHandlers(list_tasks=list_tasks_handler)
        client_ready = anyio.Event()

        try:
            async with anyio.create_task_group() as tg:

                async def run_client():
                    async with ClientSession(
                        server_to_client_receive,
                        client_to_server_send,
                        message_handler=message_handler,
                        experimental_task_handlers=task_handlers,
                    ):
                        client_ready.set()
                        await anyio.sleep_forever()

                tg.start_soon(run_client)
                await client_ready.wait()

                # Server sends ListTasksRequest to client
                request_id = "req-3"
                request = types.JSONRPCRequest(
                    jsonrpc="2.0",
                    id=request_id,
                    method="tasks/list",
                )
                await server_to_client_send.send(SessionMessage(types.JSONRPCMessage(request)))

                # Receive response
                response_msg = await client_to_server_receive.receive()
                response = response_msg.message.root
                assert isinstance(response, types.JSONRPCResponse)

                result = ListTasksResult.model_validate(response.result)
                assert len(result.tasks) == 2

                tg.cancel_scope.cancel()
        finally:
            await server_to_client_send.aclose()
            await server_to_client_receive.aclose()
            await client_to_server_send.aclose()
            await client_to_server_receive.aclose()
            store.cleanup()


@pytest.mark.anyio
async def test_client_handles_cancel_task_request() -> None:
    """Test that client can respond to CancelTaskRequest from server."""
    with anyio.fail_after(10):  # 10 second timeout
        store = InMemoryTaskStore()

        async def cancel_task_handler(
            context: RequestContext[ClientSession, None],
            params: CancelTaskRequestParams,
        ) -> CancelTaskResult | ErrorData:
            task = await store.get_task(params.taskId)
            if task is None:
                return ErrorData(code=types.INVALID_REQUEST, message=f"Task {params.taskId} not found")
            await store.update_task(params.taskId, status="cancelled")
            updated = await store.get_task(params.taskId)
            assert updated is not None
            return CancelTaskResult(
                taskId=updated.taskId,
                status=updated.status,
                createdAt=updated.createdAt,
                lastUpdatedAt=updated.lastUpdatedAt,
                ttl=updated.ttl,
            )

        # Set up streams
        server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
        client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

        # Pre-create a task
        await store.create_task(TaskMetadata(ttl=60000), task_id="task-to-cancel")

        async def message_handler(
            message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
        ) -> None:
            if isinstance(message, Exception):
                raise message

        task_handlers = ExperimentalTaskHandlers(cancel_task=cancel_task_handler)
        client_ready = anyio.Event()

        try:
            async with anyio.create_task_group() as tg:

                async def run_client():
                    async with ClientSession(
                        server_to_client_receive,
                        client_to_server_send,
                        message_handler=message_handler,
                        experimental_task_handlers=task_handlers,
                    ):
                        client_ready.set()
                        await anyio.sleep_forever()

                tg.start_soon(run_client)
                await client_ready.wait()

                # Server sends CancelTaskRequest to client
                request_id = "req-4"
                request = types.JSONRPCRequest(
                    jsonrpc="2.0",
                    id=request_id,
                    method="tasks/cancel",
                    params={"taskId": "task-to-cancel"},
                )
                await server_to_client_send.send(SessionMessage(types.JSONRPCMessage(request)))

                # Receive response
                response_msg = await client_to_server_receive.receive()
                response = response_msg.message.root
                assert isinstance(response, types.JSONRPCResponse)

                result = CancelTaskResult.model_validate(response.result)
                assert result.taskId == "task-to-cancel"
                assert result.status == "cancelled"

                tg.cancel_scope.cancel()
        finally:
            await server_to_client_send.aclose()
            await server_to_client_receive.aclose()
            await client_to_server_send.aclose()
            await client_to_server_receive.aclose()
            store.cleanup()


@pytest.mark.anyio
async def test_client_task_augmented_sampling() -> None:
    """Test that client can handle task-augmented sampling request from server.

    When server sends CreateMessageRequest with task field:
    1. Client creates a task
    2. Client returns CreateTaskResult immediately
    3. Client processes sampling in background
    4. Server polls via GetTaskRequest
    5. Server gets result via GetTaskPayloadRequest
    """
    with anyio.fail_after(10):  # 10 second timeout
        store = InMemoryTaskStore()
        sampling_completed = Event()
        created_task_id: list[str | None] = [None]
        # Use a mutable container for spawning background tasks
        # We must NOT overwrite session._task_group as it breaks the session lifecycle
        background_tg: list[TaskGroup | None] = [None]

        async def task_augmented_sampling_callback(
            context: RequestContext[ClientSession, None],
            params: CreateMessageRequestParams,
            task_metadata: TaskMetadata,
        ) -> CreateTaskResult:
            """Handle task-augmented sampling request."""
            # Create the task
            task = await store.create_task(task_metadata)
            created_task_id[0] = task.taskId

            # Process in background (simulated)
            async def do_sampling():
                result = CreateMessageResult(
                    role="assistant",
                    content=TextContent(type="text", text="Sampled response"),
                    model="test-model",
                    stopReason="endTurn",
                )
                await store.store_result(task.taskId, result)
                await store.update_task(task.taskId, status="completed")
                sampling_completed.set()

            # Spawn in the outer task group via closure reference
            # (not session._task_group which would break session lifecycle)
            assert background_tg[0] is not None
            background_tg[0].start_soon(do_sampling)

            return CreateTaskResult(task=task)

        async def get_task_handler(
            context: RequestContext[ClientSession, None],
            params: GetTaskRequestParams,
        ) -> GetTaskResult | ErrorData:
            task = await store.get_task(params.taskId)
            if task is None:
                return ErrorData(code=types.INVALID_REQUEST, message="Task not found")
            return GetTaskResult(
                taskId=task.taskId,
                status=task.status,
                statusMessage=task.statusMessage,
                createdAt=task.createdAt,
                lastUpdatedAt=task.lastUpdatedAt,
                ttl=task.ttl,
                pollInterval=task.pollInterval,
            )

        async def get_task_result_handler(
            context: RequestContext[ClientSession, None],
            params: GetTaskPayloadRequestParams,
        ) -> GetTaskPayloadResult | ErrorData:
            result = await store.get_result(params.taskId)
            if result is None:
                return ErrorData(code=types.INVALID_REQUEST, message="Result not found")
            assert isinstance(result, CreateMessageResult)
            return GetTaskPayloadResult(**result.model_dump())

        # Set up streams
        server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
        client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

        async def message_handler(
            message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
        ) -> None:
            if isinstance(message, Exception):
                raise message

        task_handlers = ExperimentalTaskHandlers(
            augmented_sampling=task_augmented_sampling_callback,
            get_task=get_task_handler,
            get_task_result=get_task_result_handler,
        )
        client_ready = anyio.Event()

        try:
            async with anyio.create_task_group() as tg:
                # Set the closure reference for background task spawning
                background_tg[0] = tg

                async def run_client():
                    async with ClientSession(
                        server_to_client_receive,
                        client_to_server_send,
                        message_handler=message_handler,
                        experimental_task_handlers=task_handlers,
                    ):
                        client_ready.set()
                        await anyio.sleep_forever()

                tg.start_soon(run_client)
                await client_ready.wait()

                # Step 1: Server sends task-augmented CreateMessageRequest
                request_id = "req-sampling"
                request = types.JSONRPCRequest(
                    jsonrpc="2.0",
                    id=request_id,
                    method="sampling/createMessage",
                    params={
                        "messages": [{"role": "user", "content": {"type": "text", "text": "Hello"}}],
                        "maxTokens": 100,
                        "task": {"ttl": 60000},
                    },
                )
                await server_to_client_send.send(SessionMessage(types.JSONRPCMessage(request)))

                # Step 2: Client should respond with CreateTaskResult
                response_msg = await client_to_server_receive.receive()
                response = response_msg.message.root
                assert isinstance(response, types.JSONRPCResponse)

                task_result = CreateTaskResult.model_validate(response.result)
                task_id = task_result.task.taskId
                assert task_id == created_task_id[0]

                # Step 3: Wait for background sampling to complete
                await sampling_completed.wait()

                # Step 4: Server polls task status
                poll_request = types.JSONRPCRequest(
                    jsonrpc="2.0",
                    id="req-poll",
                    method="tasks/get",
                    params={"taskId": task_id},
                )
                await server_to_client_send.send(SessionMessage(types.JSONRPCMessage(poll_request)))

                poll_response_msg = await client_to_server_receive.receive()
                poll_response = poll_response_msg.message.root
                assert isinstance(poll_response, types.JSONRPCResponse)

                status = GetTaskResult.model_validate(poll_response.result)
                assert status.status == "completed"

                # Step 5: Server gets result
                result_request = types.JSONRPCRequest(
                    jsonrpc="2.0",
                    id="req-result",
                    method="tasks/result",
                    params={"taskId": task_id},
                )
                await server_to_client_send.send(SessionMessage(types.JSONRPCMessage(result_request)))

                result_response_msg = await client_to_server_receive.receive()
                result_response = result_response_msg.message.root
                assert isinstance(result_response, types.JSONRPCResponse)

                # GetTaskPayloadResult is a passthrough - access raw dict
                assert isinstance(result_response.result, dict)
                final_result = result_response.result
                # The result should contain the sampling response
                assert final_result["role"] == "assistant"

                tg.cancel_scope.cancel()
        finally:
            await server_to_client_send.aclose()
            await server_to_client_receive.aclose()
            await client_to_server_send.aclose()
            await client_to_server_receive.aclose()
            store.cleanup()


@pytest.mark.anyio
async def test_client_returns_error_for_unhandled_task_request() -> None:
    """Test that client returns error when no handler is registered for task request."""
    with anyio.fail_after(10):  # 10 second timeout
        server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
        client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

        async def message_handler(
            message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
        ) -> None:
            if isinstance(message, Exception):
                raise message

        client_ready = anyio.Event()

        try:
            # Client with no task handlers (uses defaults which return errors)
            async with anyio.create_task_group() as tg:

                async def run_client():
                    async with ClientSession(
                        server_to_client_receive,
                        client_to_server_send,
                        message_handler=message_handler,
                    ):
                        client_ready.set()
                        await anyio.sleep_forever()

                tg.start_soon(run_client)
                await client_ready.wait()

                # Server sends GetTaskRequest but client has no handler
                request = types.JSONRPCRequest(
                    jsonrpc="2.0",
                    id="req-unhandled",
                    method="tasks/get",
                    params={"taskId": "nonexistent"},
                )
                await server_to_client_send.send(SessionMessage(types.JSONRPCMessage(request)))

                # Client should respond with error
                response_msg = await client_to_server_receive.receive()
                response = response_msg.message.root
                # Error responses come back as JSONRPCError, not JSONRPCResponse
                assert isinstance(response, types.JSONRPCError)
                assert (
                    "not supported" in response.error.message.lower()
                    or "method not found" in response.error.message.lower()
                )

                tg.cancel_scope.cancel()
        finally:
            await server_to_client_send.aclose()
            await server_to_client_receive.aclose()
            await client_to_server_send.aclose()
            await client_to_server_receive.aclose()
