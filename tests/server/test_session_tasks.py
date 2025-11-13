"""Tests for server session task request handling."""

import anyio
import pytest

import mcp.types as types
from examples.shared.in_memory_task_store import InMemoryTaskStore
from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage

# Mark all tests in this module to ignore memory stream cleanup warnings
# These occur with tg.cancel_scope.cancel() pattern, same as SDK's own
# create_connected_server_and_client_session in src/mcp/shared/memory.py
pytestmark = pytest.mark.filterwarnings(
    "ignore:Exception ignored.*MemoryObject.*Stream:pytest.PytestUnraisableExceptionWarning"
)


@pytest.mark.anyio
async def test_get_task_success_with_task_store():
    """Test successful GetTaskRequest when task exists."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()  # Client needs task store to announce capability
    server = Server("test", task_store=task_store)

    # Create a task in the store
    task_id = "test-task-123"
    task_meta = types.TaskMetadata(taskId=task_id)
    request = types.ClientRequest(types.PingRequest())
    await task_store.create_task(task_meta, "req-1", request.root)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    task_store=client_task_store,  # Add task store to client
                ) as client_session:
                    await client_session.initialize()

                    # Send GetTaskRequest
                    result = await client_session.send_request(
                        types.ClientRequest(types.GetTaskRequest(params=types.GetTaskParams(taskId=task_id))),
                        types.GetTaskResult,
                    )

                    assert result.taskId == task_id
                    assert result.status == "submitted"
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_get_task_not_found():
    """Test GetTaskRequest when task doesn't exist."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    task_store=client_task_store,
                ) as client_session:
                    await client_session.initialize()

                    # Try to get non-existent task
                    try:
                        await client_session.send_request(
                            types.ClientRequest(
                                types.GetTaskRequest(params=types.GetTaskParams(taskId="non-existent"))
                            ),
                            types.GetTaskResult,
                        )
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        # Should get an error
                        assert "Task not found" in str(e) or str(types.INVALID_PARAMS) in str(e)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_get_task_payload_success():
    """Test successful GetTaskPayloadRequest for completed task."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    # Create a completed task with result
    task_id = "test-task-789"
    task_meta = types.TaskMetadata(taskId=task_id)
    request = types.ClientRequest(types.PingRequest())
    await task_store.create_task(task_meta, "req-1", request.root)
    result = types.ServerResult(types.EmptyResult())
    await task_store.store_task_result(task_id, result.root)
    await task_store.update_task_status(task_id, "completed")

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    task_store=client_task_store,
                ) as client_session:
                    await client_session.initialize()

                    # Get task payload
                    payload_result = await client_session.send_request(
                        types.ClientRequest(
                            types.GetTaskPayloadRequest(params=types.GetTaskPayloadParams(taskId=task_id))
                        ),
                        types.ServerResult,
                    )

                    # Verify we got the result back
                    assert isinstance(payload_result.root, types.EmptyResult)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_get_task_payload_not_completed():
    """Test GetTaskPayloadRequest fails for non-completed task."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    # Create a task in submitted state (not completed)
    task_id = "test-task-456"
    task_meta = types.TaskMetadata(taskId=task_id)
    request = types.ClientRequest(types.PingRequest())
    await task_store.create_task(task_meta, "req-1", request.root)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    task_store=client_task_store,
                ) as client_session:
                    await client_session.initialize()

                    # Try to get payload
                    try:
                        await client_session.send_request(
                            types.ClientRequest(
                                types.GetTaskPayloadRequest(params=types.GetTaskPayloadParams(taskId=task_id))
                            ),
                            types.ServerResult,
                        )
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        # Should get an error about task not being completed
                        assert "not 'completed'" in str(e) or str(types.INVALID_PARAMS) in str(e)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_get_task_payload_not_found():
    """Test GetTaskPayloadRequest fails when task doesn't exist."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    task_store=client_task_store,
                ) as client_session:
                    await client_session.initialize()

                    # Try to get payload for non-existent task
                    try:
                        await client_session.send_request(
                            types.ClientRequest(
                                types.GetTaskPayloadRequest(params=types.GetTaskPayloadParams(taskId="non-existent"))
                            ),
                            types.ServerResult,
                        )
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        # Should get an error about task not found
                        assert "Task not found" in str(e) or str(types.INVALID_PARAMS) in str(e)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_list_tasks_empty():
    """Test ListTasksRequest with no tasks."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    task_store=client_task_store,
                ) as client_session:
                    await client_session.initialize()

                    # List tasks
                    result = await client_session.send_request(
                        types.ClientRequest(types.ListTasksRequest()),
                        types.ListTasksResult,
                    )

                    assert result.tasks == []
                    assert result.nextCursor is None
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_list_tasks_with_tasks():
    """Test ListTasksRequest with multiple tasks."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    # Create some tasks
    for i in range(3):
        task_id = f"task-{i}"
        task_meta = types.TaskMetadata(taskId=task_id, keepAlive=60000)  # 60 seconds
        request = types.ClientRequest(types.PingRequest())
        await task_store.create_task(task_meta, f"req-{i}", request.root)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    task_store=client_task_store,
                ) as client_session:
                    await client_session.initialize()

                    # List tasks
                    result = await client_session.send_request(
                        types.ClientRequest(types.ListTasksRequest()),
                        types.ListTasksResult,
                    )

                    assert len(result.tasks) == 3
                    assert all(task.taskId.startswith("task-") for task in result.tasks)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_delete_task_success():
    """Test successful DeleteTaskRequest."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    # Create a task
    task_id = "task-to-delete"
    task_meta = types.TaskMetadata(taskId=task_id)
    request = types.ClientRequest(types.PingRequest())
    await task_store.create_task(task_meta, "req-1", request.root)

    # Verify task exists
    task = await task_store.get_task(task_id)
    assert task is not None

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    task_store=client_task_store,
                ) as client_session:
                    await client_session.initialize()

                    # Delete task
                    result = await client_session.send_request(
                        types.ClientRequest(types.DeleteTaskRequest(params=types.DeleteTaskParams(taskId=task_id))),
                        types.EmptyResult,
                    )

                    assert result is not None
            finally:
                tg.cancel_scope.cancel()

    # Verify task was deleted
    task = await task_store.get_task(task_id)
    assert task is None


@pytest.mark.anyio
async def test_delete_task_not_found():
    """Test DeleteTaskRequest for non-existent task."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    task_store=client_task_store,
                ) as client_session:
                    await client_session.initialize()

                    # Try to delete non-existent task
                    try:
                        await client_session.send_request(
                            types.ClientRequest(
                                types.DeleteTaskRequest(params=types.DeleteTaskParams(taskId="non-existent"))
                            ),
                            types.EmptyResult,
                        )
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        # Should get an error
                        assert "Failed to delete task" in str(e) or str(types.INVALID_PARAMS) in str(e)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_get_task_without_capability():
    """Test GetTaskRequest fails when client hasn't announced tasks capability."""
    task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    # Create a task in the store
    task_id = "test-task-999"
    task_meta = types.TaskMetadata(taskId=task_id)
    request = types.ClientRequest(types.PingRequest())
    await task_store.create_task(task_meta, "req-1", request.root)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    # No task_store - client won't announce tasks capability
                ) as client_session:
                    await client_session.initialize()

                    # Try to send GetTaskRequest
                    try:
                        await client_session.send_request(
                            types.ClientRequest(types.GetTaskRequest(params=types.GetTaskParams(taskId=task_id))),
                            types.GetTaskResult,
                        )
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        assert "not announced tasks capability" in str(e) or str(types.INVALID_REQUEST) in str(e)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_get_task_payload_without_capability():
    """Test GetTaskPayloadRequest fails when client hasn't announced tasks capability."""
    task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    # No task_store - client won't announce tasks capability
                ) as client_session:
                    await client_session.initialize()

                    # Try to send GetTaskPayloadRequest
                    try:
                        await client_session.send_request(
                            types.ClientRequest(
                                types.GetTaskPayloadRequest(params=types.GetTaskPayloadParams(taskId="some-task"))
                            ),
                            types.ServerResult,
                        )
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        assert "not announced tasks capability" in str(e) or str(types.INVALID_REQUEST) in str(e)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_list_tasks_without_capability():
    """Test ListTasksRequest fails when client hasn't announced tasks capability."""
    task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    # No task_store - client won't announce tasks capability
                ) as client_session:
                    await client_session.initialize()

                    # Try to send ListTasksRequest
                    try:
                        await client_session.send_request(
                            types.ClientRequest(types.ListTasksRequest()),
                            types.ListTasksResult,
                        )
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        assert "not announced tasks capability" in str(e) or str(types.INVALID_REQUEST) in str(e)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_delete_task_without_capability():
    """Test DeleteTaskRequest fails when client hasn't announced tasks capability."""
    task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    # No task_store - client won't announce tasks capability
                ) as client_session:
                    await client_session.initialize()

                    # Try to send DeleteTaskRequest
                    try:
                        await client_session.send_request(
                            types.ClientRequest(
                                types.DeleteTaskRequest(params=types.DeleteTaskParams(taskId="some-task"))
                            ),
                            types.EmptyResult,
                        )
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        assert "not announced tasks capability" in str(e) or str(types.INVALID_REQUEST) in str(e)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_server_receives_request_with_task_metadata():
    """Test server creates task when receiving request with task metadata."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    # Register a simple tool handler
    @server.call_tool()
    async def handle_tool(name: str, arguments: dict[str, str]) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=f"Tool {name} called")]

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    task_store=client_task_store,
                ) as client_session:
                    await client_session.initialize()

                    # Send a request with task metadata
                    task_id = "test-task-with-metadata"
                    task_meta = types.TaskMetadata(taskId=task_id, keepAlive=60000)

                    # Use send_request with task parameter to inject task metadata
                    result = await client_session.send_request(
                        types.ClientRequest(
                            types.CallToolRequest(
                                params=types.CallToolRequestParams(name="test_tool", arguments={"arg": "value"})
                            )
                        ),
                        types.CallToolResult,
                        task=task_meta,
                    )

                    # Verify the tool was called
                    assert len(result.content) > 0

                    # Verify the task was created in the server's task store
                    server_task = await task_store.get_task(task_id)
                    assert server_task is not None
                    assert server_task.taskId == task_id
                    assert server_task.status == "submitted"
            finally:
                tg.cancel_scope.cancel()


@pytest.fixture
async def server_session():
    """Create a ServerSession for testing capability checking."""
    from_client, to_server = anyio.create_memory_object_stream[SessionMessage](1)
    from_server, to_client = anyio.create_memory_object_stream[SessionMessage](1)

    async with from_client, to_server, from_server, to_client:
        session = ServerSession(
            to_server,
            from_server,
            InitializationOptions(
                server_name="test",
                server_version="1.0.0",
                capabilities=types.ServerCapabilities(),
            ),
        )
        yield session


@pytest.mark.anyio
async def test_check_tasks_capability_no_requirements(server_session: ServerSession):
    """Test _check_tasks_capability returns True when no requirements specified."""
    required = types.ClientTasksCapability(requests=None)
    client = types.ClientTasksCapability(requests=None)

    result = server_session._check_tasks_capability(required, client)
    assert result is True


@pytest.mark.anyio
async def test_check_tasks_capability_client_missing_requests(server_session: ServerSession):
    """Test _check_tasks_capability returns False when client has no requests capability."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(sampling=types.TaskSamplingCapability(createMessage=True))
    )
    client = types.ClientTasksCapability(requests=None)

    result = server_session._check_tasks_capability(required, client)
    assert result is False


@pytest.mark.anyio
async def test_check_tasks_capability_sampling_missing(server_session: ServerSession):
    """Test _check_tasks_capability returns False when sampling capability missing."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(sampling=types.TaskSamplingCapability(createMessage=True))
    )
    client = types.ClientTasksCapability(requests=types.ClientTasksRequestsCapability(sampling=None))

    result = server_session._check_tasks_capability(required, client)
    assert result is False


@pytest.mark.anyio
async def test_check_tasks_capability_sampling_createMessage_false(server_session: ServerSession):
    """Test _check_tasks_capability returns False when sampling.createMessage is False."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(sampling=types.TaskSamplingCapability(createMessage=True))
    )
    client = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(sampling=types.TaskSamplingCapability(createMessage=False))
    )

    result = server_session._check_tasks_capability(required, client)
    assert result is False


@pytest.mark.anyio
async def test_check_tasks_capability_sampling_success(server_session: ServerSession):
    """Test _check_tasks_capability returns True when sampling capability matches."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(sampling=types.TaskSamplingCapability(createMessage=True))
    )
    client = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(sampling=types.TaskSamplingCapability(createMessage=True))
    )

    result = server_session._check_tasks_capability(required, client)
    assert result is True


@pytest.mark.anyio
async def test_check_tasks_capability_elicitation_missing(server_session: ServerSession):
    """Test _check_tasks_capability returns False when elicitation capability missing."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(elicitation=types.TaskElicitationCapability(create=True))
    )
    client = types.ClientTasksCapability(requests=types.ClientTasksRequestsCapability(elicitation=None))

    result = server_session._check_tasks_capability(required, client)
    assert result is False


@pytest.mark.anyio
async def test_check_tasks_capability_elicitation_create_false(server_session: ServerSession):
    """Test _check_tasks_capability returns False when elicitation.create is False."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(elicitation=types.TaskElicitationCapability(create=True))
    )
    client = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(elicitation=types.TaskElicitationCapability(create=False))
    )

    result = server_session._check_tasks_capability(required, client)
    assert result is False


@pytest.mark.anyio
async def test_check_tasks_capability_elicitation_success(server_session: ServerSession):
    """Test _check_tasks_capability returns True when elicitation capability matches."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(elicitation=types.TaskElicitationCapability(create=True))
    )
    client = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(elicitation=types.TaskElicitationCapability(create=True))
    )

    result = server_session._check_tasks_capability(required, client)
    assert result is True


@pytest.mark.anyio
async def test_check_tasks_capability_roots_missing(server_session: ServerSession):
    """Test _check_tasks_capability returns False when roots capability missing."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(roots=types.TaskRootsCapability(list=True))
    )
    client = types.ClientTasksCapability(requests=types.ClientTasksRequestsCapability(roots=None))

    result = server_session._check_tasks_capability(required, client)
    assert result is False


@pytest.mark.anyio
async def test_check_tasks_capability_roots_list_false(server_session: ServerSession):
    """Test _check_tasks_capability returns False when roots.list is False."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(roots=types.TaskRootsCapability(list=True))
    )
    client = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(roots=types.TaskRootsCapability(list=False))
    )

    result = server_session._check_tasks_capability(required, client)
    assert result is False


@pytest.mark.anyio
async def test_check_tasks_capability_roots_success(server_session: ServerSession):
    """Test _check_tasks_capability returns True when roots capability matches."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(roots=types.TaskRootsCapability(list=True))
    )
    client = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(roots=types.TaskRootsCapability(list=True))
    )

    result = server_session._check_tasks_capability(required, client)
    assert result is True


@pytest.mark.anyio
async def test_check_tasks_capability_tasks_missing(server_session: ServerSession):
    """Test _check_tasks_capability returns False when tasks capability missing."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(
            tasks=types.TasksOperationsCapability(get=True, list=True, result=True, delete=True)
        )
    )
    client = types.ClientTasksCapability(requests=types.ClientTasksRequestsCapability(tasks=None))

    result = server_session._check_tasks_capability(required, client)
    assert result is False


@pytest.mark.anyio
async def test_check_tasks_capability_tasks_get_false(server_session: ServerSession):
    """Test _check_tasks_capability returns False when tasks.get is False."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(
            tasks=types.TasksOperationsCapability(get=True, list=False, result=False, delete=False)
        )
    )
    client = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(
            tasks=types.TasksOperationsCapability(get=False, list=True, result=True, delete=True)
        )
    )

    result = server_session._check_tasks_capability(required, client)
    assert result is False


@pytest.mark.anyio
async def test_check_tasks_capability_tasks_list_false(server_session: ServerSession):
    """Test _check_tasks_capability returns False when tasks.list is False."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(
            tasks=types.TasksOperationsCapability(get=False, list=True, result=False, delete=False)
        )
    )
    client = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(
            tasks=types.TasksOperationsCapability(get=True, list=False, result=True, delete=True)
        )
    )

    result = server_session._check_tasks_capability(required, client)
    assert result is False


@pytest.mark.anyio
async def test_check_tasks_capability_tasks_result_false(server_session: ServerSession):
    """Test _check_tasks_capability returns False when tasks.result is False."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(
            tasks=types.TasksOperationsCapability(get=False, list=False, result=True, delete=False)
        )
    )
    client = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(
            tasks=types.TasksOperationsCapability(get=True, list=True, result=False, delete=True)
        )
    )

    result = server_session._check_tasks_capability(required, client)
    assert result is False


@pytest.mark.anyio
async def test_check_tasks_capability_tasks_delete_false(server_session: ServerSession):
    """Test _check_tasks_capability returns False when tasks.delete is False."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(
            tasks=types.TasksOperationsCapability(get=False, list=False, result=False, delete=True)
        )
    )
    client = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(
            tasks=types.TasksOperationsCapability(get=True, list=True, result=True, delete=False)
        )
    )

    result = server_session._check_tasks_capability(required, client)
    assert result is False


@pytest.mark.anyio
async def test_check_tasks_capability_tasks_all_operations_true(server_session: ServerSession):
    """Test _check_tasks_capability returns True when all required task operations match."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(
            tasks=types.TasksOperationsCapability(get=True, list=True, result=True, delete=True)
        )
    )
    client = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(
            tasks=types.TasksOperationsCapability(get=True, list=True, result=True, delete=True)
        )
    )

    result = server_session._check_tasks_capability(required, client)
    assert result is True


@pytest.mark.anyio
async def test_check_tasks_capability_all_capabilities_present(server_session: ServerSession):
    """Test _check_tasks_capability returns True when all capabilities are satisfied."""
    required = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(
            sampling=types.TaskSamplingCapability(createMessage=True),
            elicitation=types.TaskElicitationCapability(create=True),
            roots=types.TaskRootsCapability(list=True),
            tasks=types.TasksOperationsCapability(get=True, list=True, result=True, delete=True),
        )
    )
    client = types.ClientTasksCapability(
        requests=types.ClientTasksRequestsCapability(
            sampling=types.TaskSamplingCapability(createMessage=True),
            elicitation=types.TaskElicitationCapability(create=True),
            roots=types.TaskRootsCapability(list=True),
            tasks=types.TasksOperationsCapability(get=True, list=True, result=True, delete=True),
        )
    )

    result = server_session._check_tasks_capability(required, client)
    assert result is True


@pytest.mark.anyio
async def test_get_task_without_task_store():
    """Test GetTaskRequest fails when server has no task store configured."""
    client_task_store = InMemoryTaskStore()
    server = Server("test")  # No task_store parameter

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    task_store=client_task_store,
                ) as client_session:
                    await client_session.initialize()

                    # Try to send GetTaskRequest
                    try:
                        await client_session.send_request(
                            types.ClientRequest(types.GetTaskRequest(params=types.GetTaskParams(taskId="test-task"))),
                            types.GetTaskResult,
                        )
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        assert "Task store not configured" in str(e) or str(types.INVALID_REQUEST) in str(e)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_get_task_payload_without_task_store():
    """Test GetTaskPayloadRequest fails when server has no task store configured."""
    client_task_store = InMemoryTaskStore()
    server = Server("test")  # No task_store parameter

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    task_store=client_task_store,
                ) as client_session:
                    await client_session.initialize()

                    # Try to send GetTaskPayloadRequest
                    try:
                        await client_session.send_request(
                            types.ClientRequest(
                                types.GetTaskPayloadRequest(params=types.GetTaskPayloadParams(taskId="test-task"))
                            ),
                            types.ServerResult,
                        )
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        assert "Task store not configured" in str(e) or str(types.INVALID_REQUEST) in str(e)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_list_tasks_without_task_store():
    """Test ListTasksRequest fails when server has no task store configured."""
    client_task_store = InMemoryTaskStore()
    server = Server("test")  # No task_store parameter

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    task_store=client_task_store,
                ) as client_session:
                    await client_session.initialize()

                    # Try to send ListTasksRequest
                    try:
                        await client_session.send_request(
                            types.ClientRequest(types.ListTasksRequest()),
                            types.ListTasksResult,
                        )
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        assert "Task store not configured" in str(e) or str(types.INVALID_REQUEST) in str(e)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_delete_task_without_task_store():
    """Test DeleteTaskRequest fails when server has no task store configured."""
    client_task_store = InMemoryTaskStore()
    server = Server("test")  # No task_store parameter

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )
            )

            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    task_store=client_task_store,
                ) as client_session:
                    await client_session.initialize()

                    # Try to send DeleteTaskRequest
                    try:
                        await client_session.send_request(
                            types.ClientRequest(
                                types.DeleteTaskRequest(params=types.DeleteTaskParams(taskId="test-task"))
                            ),
                            types.EmptyResult,
                        )
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        assert "Task store not configured" in str(e) or str(types.INVALID_REQUEST) in str(e)
            finally:
                tg.cancel_scope.cancel()
