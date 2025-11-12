"""Tests for server session task request handling."""

import anyio
import pytest

import mcp.types as types
from examples.shared.in_memory_task_store import InMemoryTaskStore
from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.shared.memory import create_client_server_memory_streams


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
