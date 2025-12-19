"""Tests for client-side task management handlers (server -> client requests).

These tests verify that clients can handle task-related requests from servers:
- GetTaskRequest - server polling client's task status
- GetTaskPayloadRequest - server getting result from client's task
- ListTasksRequest - server listing client's tasks
- CancelTaskRequest - server cancelling client's task

This is the inverse of the existing tests in test_tasks.py, which test
client -> server task requests.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import anyio
import pytest
from anyio import Event
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

import mcp.types as types
from mcp.client.experimental.task_handlers import ExperimentalTaskHandlers
from mcp.client.session import ClientSession
from mcp.shared.context import RequestContext
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    CancelTaskRequest,
    CancelTaskRequestParams,
    CancelTaskResult,
    ClientResult,
    CreateMessageRequest,
    CreateMessageRequestParams,
    CreateMessageResult,
    CreateTaskResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitRequestParams,
    ElicitResult,
    ErrorData,
    GetTaskPayloadRequest,
    GetTaskPayloadRequestParams,
    GetTaskPayloadResult,
    GetTaskRequest,
    GetTaskRequestParams,
    GetTaskResult,
    ListTasksRequest,
    ListTasksResult,
    SamplingMessage,
    ServerNotification,
    ServerRequest,
    TaskMetadata,
    TextContent,
)

# Buffer size for test streams
STREAM_BUFFER_SIZE = 10


@dataclass
class ClientTestStreams:
    """Bidirectional message streams for client/server communication in tests."""

    server_send: MemoryObjectSendStream[SessionMessage]
    server_receive: MemoryObjectReceiveStream[SessionMessage]
    client_send: MemoryObjectSendStream[SessionMessage]
    client_receive: MemoryObjectReceiveStream[SessionMessage]


@pytest.fixture
async def client_streams() -> AsyncIterator[ClientTestStreams]:
    """Create bidirectional message streams for client tests.

    Automatically closes all streams after the test completes.
    """
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](
        STREAM_BUFFER_SIZE
    )
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](
        STREAM_BUFFER_SIZE
    )

    streams = ClientTestStreams(
        server_send=server_to_client_send,
        server_receive=client_to_server_receive,
        client_send=client_to_server_send,
        client_receive=server_to_client_receive,
    )

    yield streams

    # Cleanup
    await server_to_client_send.aclose()
    await server_to_client_receive.aclose()
    await client_to_server_send.aclose()
    await client_to_server_receive.aclose()


async def _default_message_handler(
    message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
) -> None:
    """Default message handler that ignores messages (tests handle them explicitly)."""
    ...


@pytest.mark.anyio
async def test_client_handles_get_task_request(client_streams: ClientTestStreams) -> None:
    """Test that client can respond to GetTaskRequest from server."""
    with anyio.fail_after(10):
        store = InMemoryTaskStore()
        received_task_id: str | None = None

        async def get_task_handler(
            context: RequestContext[ClientSession, None],
            params: GetTaskRequestParams,
        ) -> GetTaskResult | ErrorData:
            nonlocal received_task_id
            received_task_id = params.taskId
            task = await store.get_task(params.taskId)
            assert task is not None, f"Test setup error: task {params.taskId} should exist"
            return GetTaskResult(
                taskId=task.taskId,
                status=task.status,
                statusMessage=task.statusMessage,
                createdAt=task.createdAt,
                lastUpdatedAt=task.lastUpdatedAt,
                ttl=task.ttl,
                pollInterval=task.pollInterval,
            )

        await store.create_task(TaskMetadata(ttl=60000), task_id="test-task-123")

        task_handlers = ExperimentalTaskHandlers(get_task=get_task_handler)
        client_ready = anyio.Event()

        async with anyio.create_task_group() as tg:

            async def run_client() -> None:
                async with ClientSession(
                    client_streams.client_receive,
                    client_streams.client_send,
                    message_handler=_default_message_handler,
                    experimental_task_handlers=task_handlers,
                ):
                    client_ready.set()
                    await anyio.sleep_forever()

            tg.start_soon(run_client)
            await client_ready.wait()

            typed_request = GetTaskRequest(params=GetTaskRequestParams(taskId="test-task-123"))
            request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-1",
                **typed_request.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(request)))

            response_msg = await client_streams.server_receive.receive()
            response = response_msg.message.root
            assert isinstance(response, types.JSONRPCResponse)
            assert response.id == "req-1"

            result = GetTaskResult.model_validate(response.result)
            assert result.taskId == "test-task-123"
            assert result.status == "working"
            assert received_task_id == "test-task-123"

            tg.cancel_scope.cancel()

        store.cleanup()


@pytest.mark.anyio
async def test_client_handles_get_task_result_request(client_streams: ClientTestStreams) -> None:
    """Test that client can respond to GetTaskPayloadRequest from server."""
    with anyio.fail_after(10):
        store = InMemoryTaskStore()

        async def get_task_result_handler(
            context: RequestContext[ClientSession, None],
            params: GetTaskPayloadRequestParams,
        ) -> GetTaskPayloadResult | ErrorData:
            result = await store.get_result(params.taskId)
            assert result is not None, f"Test setup error: result for {params.taskId} should exist"
            assert isinstance(result, types.CallToolResult)
            return GetTaskPayloadResult(**result.model_dump())

        await store.create_task(TaskMetadata(ttl=60000), task_id="test-task-456")
        await store.store_result(
            "test-task-456",
            types.CallToolResult(content=[TextContent(type="text", text="Task completed successfully!")]),
        )
        await store.update_task("test-task-456", status="completed")

        task_handlers = ExperimentalTaskHandlers(get_task_result=get_task_result_handler)
        client_ready = anyio.Event()

        async with anyio.create_task_group() as tg:

            async def run_client() -> None:
                async with ClientSession(
                    client_streams.client_receive,
                    client_streams.client_send,
                    message_handler=_default_message_handler,
                    experimental_task_handlers=task_handlers,
                ):
                    client_ready.set()
                    await anyio.sleep_forever()

            tg.start_soon(run_client)
            await client_ready.wait()

            typed_request = GetTaskPayloadRequest(params=GetTaskPayloadRequestParams(taskId="test-task-456"))
            request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-2",
                **typed_request.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(request)))

            response_msg = await client_streams.server_receive.receive()
            response = response_msg.message.root
            assert isinstance(response, types.JSONRPCResponse)

            assert isinstance(response.result, dict)
            result_dict = response.result
            assert "content" in result_dict
            assert len(result_dict["content"]) == 1
            assert result_dict["content"][0]["text"] == "Task completed successfully!"

            tg.cancel_scope.cancel()

        store.cleanup()


@pytest.mark.anyio
async def test_client_handles_list_tasks_request(client_streams: ClientTestStreams) -> None:
    """Test that client can respond to ListTasksRequest from server."""
    with anyio.fail_after(10):
        store = InMemoryTaskStore()

        async def list_tasks_handler(
            context: RequestContext[ClientSession, None],
            params: types.PaginatedRequestParams | None,
        ) -> ListTasksResult | ErrorData:
            cursor = params.cursor if params else None
            tasks_list, next_cursor = await store.list_tasks(cursor=cursor)
            return ListTasksResult(tasks=tasks_list, nextCursor=next_cursor)

        await store.create_task(TaskMetadata(ttl=60000), task_id="task-1")
        await store.create_task(TaskMetadata(ttl=60000), task_id="task-2")

        task_handlers = ExperimentalTaskHandlers(list_tasks=list_tasks_handler)
        client_ready = anyio.Event()

        async with anyio.create_task_group() as tg:

            async def run_client() -> None:
                async with ClientSession(
                    client_streams.client_receive,
                    client_streams.client_send,
                    message_handler=_default_message_handler,
                    experimental_task_handlers=task_handlers,
                ):
                    client_ready.set()
                    await anyio.sleep_forever()

            tg.start_soon(run_client)
            await client_ready.wait()

            typed_request = ListTasksRequest()
            request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-3",
                **typed_request.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(request)))

            response_msg = await client_streams.server_receive.receive()
            response = response_msg.message.root
            assert isinstance(response, types.JSONRPCResponse)

            result = ListTasksResult.model_validate(response.result)
            assert len(result.tasks) == 2

            tg.cancel_scope.cancel()

        store.cleanup()


@pytest.mark.anyio
async def test_client_handles_cancel_task_request(client_streams: ClientTestStreams) -> None:
    """Test that client can respond to CancelTaskRequest from server."""
    with anyio.fail_after(10):
        store = InMemoryTaskStore()

        async def cancel_task_handler(
            context: RequestContext[ClientSession, None],
            params: CancelTaskRequestParams,
        ) -> CancelTaskResult | ErrorData:
            task = await store.get_task(params.taskId)
            assert task is not None, f"Test setup error: task {params.taskId} should exist"
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

        await store.create_task(TaskMetadata(ttl=60000), task_id="task-to-cancel")

        task_handlers = ExperimentalTaskHandlers(cancel_task=cancel_task_handler)
        client_ready = anyio.Event()

        async with anyio.create_task_group() as tg:

            async def run_client() -> None:
                async with ClientSession(
                    client_streams.client_receive,
                    client_streams.client_send,
                    message_handler=_default_message_handler,
                    experimental_task_handlers=task_handlers,
                ):
                    client_ready.set()
                    await anyio.sleep_forever()

            tg.start_soon(run_client)
            await client_ready.wait()

            typed_request = CancelTaskRequest(params=CancelTaskRequestParams(taskId="task-to-cancel"))
            request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-4",
                **typed_request.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(request)))

            response_msg = await client_streams.server_receive.receive()
            response = response_msg.message.root
            assert isinstance(response, types.JSONRPCResponse)

            result = CancelTaskResult.model_validate(response.result)
            assert result.taskId == "task-to-cancel"
            assert result.status == "cancelled"

            tg.cancel_scope.cancel()

        store.cleanup()


@pytest.mark.anyio
async def test_client_task_augmented_sampling(client_streams: ClientTestStreams) -> None:
    """Test that client can handle task-augmented sampling request from server."""
    with anyio.fail_after(10):
        store = InMemoryTaskStore()
        sampling_completed = Event()
        created_task_id: list[str | None] = [None]
        background_tg: list[TaskGroup | None] = [None]

        async def task_augmented_sampling_callback(
            context: RequestContext[ClientSession, None],
            params: CreateMessageRequestParams,
            task_metadata: TaskMetadata,
        ) -> CreateTaskResult:
            task = await store.create_task(task_metadata)
            created_task_id[0] = task.taskId

            async def do_sampling() -> None:
                result = CreateMessageResult(
                    role="assistant",
                    content=TextContent(type="text", text="Sampled response"),
                    model="test-model",
                    stopReason="endTurn",
                )
                await store.store_result(task.taskId, result)
                await store.update_task(task.taskId, status="completed")
                sampling_completed.set()

            assert background_tg[0] is not None
            background_tg[0].start_soon(do_sampling)
            return CreateTaskResult(task=task)

        async def get_task_handler(
            context: RequestContext[ClientSession, None],
            params: GetTaskRequestParams,
        ) -> GetTaskResult | ErrorData:
            task = await store.get_task(params.taskId)
            assert task is not None, f"Test setup error: task {params.taskId} should exist"
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
            assert result is not None, f"Test setup error: result for {params.taskId} should exist"
            assert isinstance(result, CreateMessageResult)
            return GetTaskPayloadResult(**result.model_dump())

        task_handlers = ExperimentalTaskHandlers(
            augmented_sampling=task_augmented_sampling_callback,
            get_task=get_task_handler,
            get_task_result=get_task_result_handler,
        )
        client_ready = anyio.Event()

        async with anyio.create_task_group() as tg:
            background_tg[0] = tg

            async def run_client() -> None:
                async with ClientSession(
                    client_streams.client_receive,
                    client_streams.client_send,
                    message_handler=_default_message_handler,
                    experimental_task_handlers=task_handlers,
                ):
                    client_ready.set()
                    await anyio.sleep_forever()

            tg.start_soon(run_client)
            await client_ready.wait()

            # Step 1: Server sends task-augmented CreateMessageRequest
            typed_request = CreateMessageRequest(
                params=CreateMessageRequestParams(
                    messages=[SamplingMessage(role="user", content=TextContent(type="text", text="Hello"))],
                    maxTokens=100,
                    task=TaskMetadata(ttl=60000),
                )
            )
            request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-sampling",
                **typed_request.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(request)))

            # Step 2: Client responds with CreateTaskResult
            response_msg = await client_streams.server_receive.receive()
            response = response_msg.message.root
            assert isinstance(response, types.JSONRPCResponse)

            task_result = CreateTaskResult.model_validate(response.result)
            task_id = task_result.task.taskId
            assert task_id == created_task_id[0]

            # Step 3: Wait for background sampling
            await sampling_completed.wait()

            # Step 4: Server polls task status
            typed_poll = GetTaskRequest(params=GetTaskRequestParams(taskId=task_id))
            poll_request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-poll",
                **typed_poll.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(poll_request)))

            poll_response_msg = await client_streams.server_receive.receive()
            poll_response = poll_response_msg.message.root
            assert isinstance(poll_response, types.JSONRPCResponse)

            status = GetTaskResult.model_validate(poll_response.result)
            assert status.status == "completed"

            # Step 5: Server gets result
            typed_result_req = GetTaskPayloadRequest(params=GetTaskPayloadRequestParams(taskId=task_id))
            result_request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-result",
                **typed_result_req.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(result_request)))

            result_response_msg = await client_streams.server_receive.receive()
            result_response = result_response_msg.message.root
            assert isinstance(result_response, types.JSONRPCResponse)

            assert isinstance(result_response.result, dict)
            assert result_response.result["role"] == "assistant"

            tg.cancel_scope.cancel()

        store.cleanup()


@pytest.mark.anyio
async def test_client_task_augmented_elicitation(client_streams: ClientTestStreams) -> None:
    """Test that client can handle task-augmented elicitation request from server."""
    with anyio.fail_after(10):
        store = InMemoryTaskStore()
        elicitation_completed = Event()
        created_task_id: list[str | None] = [None]
        background_tg: list[TaskGroup | None] = [None]

        async def task_augmented_elicitation_callback(
            context: RequestContext[ClientSession, None],
            params: ElicitRequestParams,
            task_metadata: TaskMetadata,
        ) -> CreateTaskResult | ErrorData:
            task = await store.create_task(task_metadata)
            created_task_id[0] = task.taskId

            async def do_elicitation() -> None:
                # Simulate user providing elicitation response
                result = ElicitResult(action="accept", content={"name": "Test User"})
                await store.store_result(task.taskId, result)
                await store.update_task(task.taskId, status="completed")
                elicitation_completed.set()

            assert background_tg[0] is not None
            background_tg[0].start_soon(do_elicitation)
            return CreateTaskResult(task=task)

        async def get_task_handler(
            context: RequestContext[ClientSession, None],
            params: GetTaskRequestParams,
        ) -> GetTaskResult | ErrorData:
            task = await store.get_task(params.taskId)
            assert task is not None, f"Test setup error: task {params.taskId} should exist"
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
            assert result is not None, f"Test setup error: result for {params.taskId} should exist"
            assert isinstance(result, ElicitResult)
            return GetTaskPayloadResult(**result.model_dump())

        task_handlers = ExperimentalTaskHandlers(
            augmented_elicitation=task_augmented_elicitation_callback,
            get_task=get_task_handler,
            get_task_result=get_task_result_handler,
        )
        client_ready = anyio.Event()

        async with anyio.create_task_group() as tg:
            background_tg[0] = tg

            async def run_client() -> None:
                async with ClientSession(
                    client_streams.client_receive,
                    client_streams.client_send,
                    message_handler=_default_message_handler,
                    experimental_task_handlers=task_handlers,
                ):
                    client_ready.set()
                    await anyio.sleep_forever()

            tg.start_soon(run_client)
            await client_ready.wait()

            # Step 1: Server sends task-augmented ElicitRequest
            typed_request = ElicitRequest(
                params=ElicitRequestFormParams(
                    message="What is your name?",
                    requestedSchema={"type": "object", "properties": {"name": {"type": "string"}}},
                    task=TaskMetadata(ttl=60000),
                )
            )
            request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-elicit",
                **typed_request.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(request)))

            # Step 2: Client responds with CreateTaskResult
            response_msg = await client_streams.server_receive.receive()
            response = response_msg.message.root
            assert isinstance(response, types.JSONRPCResponse)

            task_result = CreateTaskResult.model_validate(response.result)
            task_id = task_result.task.taskId
            assert task_id == created_task_id[0]

            # Step 3: Wait for background elicitation
            await elicitation_completed.wait()

            # Step 4: Server polls task status
            typed_poll = GetTaskRequest(params=GetTaskRequestParams(taskId=task_id))
            poll_request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-poll",
                **typed_poll.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(poll_request)))

            poll_response_msg = await client_streams.server_receive.receive()
            poll_response = poll_response_msg.message.root
            assert isinstance(poll_response, types.JSONRPCResponse)

            status = GetTaskResult.model_validate(poll_response.result)
            assert status.status == "completed"

            # Step 5: Server gets result
            typed_result_req = GetTaskPayloadRequest(params=GetTaskPayloadRequestParams(taskId=task_id))
            result_request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-result",
                **typed_result_req.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(result_request)))

            result_response_msg = await client_streams.server_receive.receive()
            result_response = result_response_msg.message.root
            assert isinstance(result_response, types.JSONRPCResponse)

            # Verify the elicitation result
            assert isinstance(result_response.result, dict)
            assert result_response.result["action"] == "accept"
            assert result_response.result["content"] == {"name": "Test User"}

            tg.cancel_scope.cancel()

        store.cleanup()


@pytest.mark.anyio
async def test_client_returns_error_for_unhandled_task_request(client_streams: ClientTestStreams) -> None:
    """Test that client returns error when no handler is registered for task request."""
    with anyio.fail_after(10):
        client_ready = anyio.Event()

        async with anyio.create_task_group() as tg:

            async def run_client() -> None:
                async with ClientSession(
                    client_streams.client_receive,
                    client_streams.client_send,
                    message_handler=_default_message_handler,
                ):
                    client_ready.set()
                    await anyio.sleep_forever()

            tg.start_soon(run_client)
            await client_ready.wait()

            typed_request = GetTaskRequest(params=GetTaskRequestParams(taskId="nonexistent"))
            request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-unhandled",
                **typed_request.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(request)))

            response_msg = await client_streams.server_receive.receive()
            response = response_msg.message.root
            assert isinstance(response, types.JSONRPCError)
            assert (
                "not supported" in response.error.message.lower()
                or "method not found" in response.error.message.lower()
            )

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_client_returns_error_for_unhandled_task_result_request(client_streams: ClientTestStreams) -> None:
    """Test that client returns error for unhandled tasks/result request."""
    with anyio.fail_after(10):
        client_ready = anyio.Event()

        async with anyio.create_task_group() as tg:

            async def run_client() -> None:
                async with ClientSession(
                    client_streams.client_receive,
                    client_streams.client_send,
                    message_handler=_default_message_handler,
                ):
                    client_ready.set()
                    await anyio.sleep_forever()

            tg.start_soon(run_client)
            await client_ready.wait()

            typed_request = GetTaskPayloadRequest(params=GetTaskPayloadRequestParams(taskId="nonexistent"))
            request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-result",
                **typed_request.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(request)))

            response_msg = await client_streams.server_receive.receive()
            response = response_msg.message.root
            assert isinstance(response, types.JSONRPCError)
            assert "not supported" in response.error.message.lower()

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_client_returns_error_for_unhandled_list_tasks_request(client_streams: ClientTestStreams) -> None:
    """Test that client returns error for unhandled tasks/list request."""
    with anyio.fail_after(10):
        client_ready = anyio.Event()

        async with anyio.create_task_group() as tg:

            async def run_client() -> None:
                async with ClientSession(
                    client_streams.client_receive,
                    client_streams.client_send,
                    message_handler=_default_message_handler,
                ):
                    client_ready.set()
                    await anyio.sleep_forever()

            tg.start_soon(run_client)
            await client_ready.wait()

            typed_request = ListTasksRequest()
            request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-list",
                **typed_request.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(request)))

            response_msg = await client_streams.server_receive.receive()
            response = response_msg.message.root
            assert isinstance(response, types.JSONRPCError)
            assert "not supported" in response.error.message.lower()

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_client_returns_error_for_unhandled_cancel_task_request(client_streams: ClientTestStreams) -> None:
    """Test that client returns error for unhandled tasks/cancel request."""
    with anyio.fail_after(10):
        client_ready = anyio.Event()

        async with anyio.create_task_group() as tg:

            async def run_client() -> None:
                async with ClientSession(
                    client_streams.client_receive,
                    client_streams.client_send,
                    message_handler=_default_message_handler,
                ):
                    client_ready.set()
                    await anyio.sleep_forever()

            tg.start_soon(run_client)
            await client_ready.wait()

            typed_request = CancelTaskRequest(params=CancelTaskRequestParams(taskId="nonexistent"))
            request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-cancel",
                **typed_request.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(request)))

            response_msg = await client_streams.server_receive.receive()
            response = response_msg.message.root
            assert isinstance(response, types.JSONRPCError)
            assert "not supported" in response.error.message.lower()

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_client_returns_error_for_unhandled_task_augmented_sampling(client_streams: ClientTestStreams) -> None:
    """Test that client returns error for task-augmented sampling without handler."""
    with anyio.fail_after(10):
        client_ready = anyio.Event()

        async with anyio.create_task_group() as tg:

            async def run_client() -> None:
                # No task handlers provided - uses defaults
                async with ClientSession(
                    client_streams.client_receive,
                    client_streams.client_send,
                    message_handler=_default_message_handler,
                ):
                    client_ready.set()
                    await anyio.sleep_forever()

            tg.start_soon(run_client)
            await client_ready.wait()

            # Send task-augmented sampling request
            typed_request = CreateMessageRequest(
                params=CreateMessageRequestParams(
                    messages=[SamplingMessage(role="user", content=TextContent(type="text", text="Hello"))],
                    maxTokens=100,
                    task=TaskMetadata(ttl=60000),
                )
            )
            request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-sampling",
                **typed_request.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(request)))

            response_msg = await client_streams.server_receive.receive()
            response = response_msg.message.root
            assert isinstance(response, types.JSONRPCError)
            assert "not supported" in response.error.message.lower()

            tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_client_returns_error_for_unhandled_task_augmented_elicitation(
    client_streams: ClientTestStreams,
) -> None:
    """Test that client returns error for task-augmented elicitation without handler."""
    with anyio.fail_after(10):
        client_ready = anyio.Event()

        async with anyio.create_task_group() as tg:

            async def run_client() -> None:
                # No task handlers provided - uses defaults
                async with ClientSession(
                    client_streams.client_receive,
                    client_streams.client_send,
                    message_handler=_default_message_handler,
                ):
                    client_ready.set()
                    await anyio.sleep_forever()

            tg.start_soon(run_client)
            await client_ready.wait()

            # Send task-augmented elicitation request
            typed_request = ElicitRequest(
                params=ElicitRequestFormParams(
                    message="What is your name?",
                    requestedSchema={"type": "object", "properties": {"name": {"type": "string"}}},
                    task=TaskMetadata(ttl=60000),
                )
            )
            request = types.JSONRPCRequest(
                jsonrpc="2.0",
                id="req-elicit",
                **typed_request.model_dump(by_alias=True),
            )
            await client_streams.server_send.send(SessionMessage(types.JSONRPCMessage(request)))

            response_msg = await client_streams.server_receive.receive()
            response = response_msg.message.root
            assert isinstance(response, types.JSONRPCError)
            assert "not supported" in response.error.message.lower()

            tg.cancel_scope.cancel()
