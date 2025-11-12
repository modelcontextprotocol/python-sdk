"""Tests for client session task methods."""

import anyio
import pytest

import mcp.types as types
from examples.shared.in_memory_task_store import InMemoryTaskStore
from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.shared.memory import create_client_server_memory_streams


@pytest.mark.anyio
async def test_client_get_task_success():
    """Test client.get_task() method with existing task."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    # Create a task in the server's store
    task_id = "test-task-123"
    task_meta = types.TaskMetadata(taskId=task_id, keepAlive=60000)
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

                    # Call get_task method
                    result = await client_session.get_task(task_id)

                    assert result.taskId == task_id
                    assert result.status == "submitted"
                    assert result.keepAlive == 60000
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_client_get_task_not_found():
    """Test client.get_task() method when task doesn't exist."""
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
                        await client_session.get_task("non-existent")
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        assert "Task not found" in str(e) or str(types.INVALID_PARAMS) in str(e)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_client_get_task_result_success():
    """Test client.get_task_result() method for completed task."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    # Create a completed task with result
    task_id = "test-task-789"
    task_meta = types.TaskMetadata(taskId=task_id, keepAlive=60000)
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

                    # Get task result
                    payload_result = await client_session.get_task_result(task_id, types.ServerResult)

                    # Verify we got the result back
                    assert isinstance(payload_result.root, types.EmptyResult)  # type: ignore[attr-defined]
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_client_get_task_result_not_completed():
    """Test client.get_task_result() method fails for non-completed task."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    # Create a task in submitted state (not completed)
    task_id = "test-task-456"
    task_meta = types.TaskMetadata(taskId=task_id, keepAlive=60000)
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

                    # Try to get result
                    try:
                        await client_session.get_task_result(task_id, types.ServerResult)
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        assert "not 'completed'" in str(e) or str(types.INVALID_PARAMS) in str(e)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_client_list_tasks_empty():
    """Test client.list_tasks() method with no tasks."""
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
                    result = await client_session.list_tasks()

                    assert result.tasks == []
                    assert result.nextCursor is None
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_client_list_tasks_with_tasks():
    """Test client.list_tasks() method with multiple tasks."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    # Create some tasks
    for i in range(3):
        task_id = f"task-{i}"
        task_meta = types.TaskMetadata(taskId=task_id, keepAlive=60000)
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
                    result = await client_session.list_tasks()

                    assert len(result.tasks) == 3
                    assert all(task.taskId.startswith("task-") for task in result.tasks)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_client_list_tasks_with_cursor():
    """Test client.list_tasks() method with pagination cursor."""
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

                    # List tasks with invalid cursor should raise error
                    try:
                        await client_session.list_tasks(cursor="invalid-cursor")
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        assert "Invalid cursor" in str(e) or str(types.INVALID_PARAMS) in str(e)
            finally:
                tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_client_delete_task_success():
    """Test client.delete_task() method."""
    task_store = InMemoryTaskStore()
    client_task_store = InMemoryTaskStore()
    server = Server("test", task_store=task_store)

    # Create a task
    task_id = "task-to-delete"
    task_meta = types.TaskMetadata(taskId=task_id, keepAlive=60000)
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
                    result = await client_session.delete_task(task_id)

                    assert result is not None
            finally:
                tg.cancel_scope.cancel()

    # Verify task was deleted
    task = await task_store.get_task(task_id)
    assert task is None


@pytest.mark.anyio
async def test_client_delete_task_not_found():
    """Test client.delete_task() method for non-existent task."""
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
                        await client_session.delete_task("non-existent")
                        assert False, "Should have raised McpError"
                    except Exception as e:
                        assert "Failed to delete task" in str(e) or str(types.INVALID_PARAMS) in str(e)
            finally:
                tg.cancel_scope.cancel()
