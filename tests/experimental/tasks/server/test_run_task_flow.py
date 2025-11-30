"""
Tests for the simplified task API: enable_tasks() + run_task()

This tests the recommended user flow:
1. server.experimental.enable_tasks() - one-line setup
2. ctx.experimental.run_task(work) - spawns work, returns CreateTaskResult
3. work function uses ServerTaskContext for elicit/create_message

These are integration tests that verify the complete flow works end-to-end.
"""

from typing import Any
from unittest.mock import Mock

import anyio
import pytest
from anyio import Event

from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.experimental.request_context import Experimental
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.server.experimental.task_support import TaskSupport
from mcp.server.lowlevel import NotificationOptions
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.experimental.tasks.message_queue import InMemoryTaskMessageQueue
from mcp.shared.message import SessionMessage
from mcp.types import (
    TASK_REQUIRED,
    CallToolResult,
    CancelTaskRequest,
    CancelTaskResult,
    CreateTaskResult,
    GetTaskPayloadRequest,
    GetTaskPayloadResult,
    GetTaskRequest,
    GetTaskResult,
    ListTasksRequest,
    ListTasksResult,
    TextContent,
    Tool,
    ToolExecution,
)


@pytest.mark.anyio
async def test_run_task_basic_flow() -> None:
    """
    Test the basic run_task flow without elicitation.

    1. enable_tasks() sets up handlers
    2. Client calls tool with task field
    3. run_task() spawns work, returns CreateTaskResult
    4. Work completes in background
    5. Client polls and sees completed status
    """
    server = Server("test-run-task")

    # One-line setup
    server.experimental.enable_tasks()

    # Track when work completes and capture received meta
    work_completed = Event()
    received_meta: list[str | None] = [None]

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="simple_task",
                description="A simple task",
                inputSchema={"type": "object", "properties": {"input": {"type": "string"}}},
                execution=ToolExecution(taskSupport=TASK_REQUIRED),
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult | CreateTaskResult:
        ctx = server.request_context
        ctx.experimental.validate_task_mode(TASK_REQUIRED)

        # Capture the meta from the request (if present)
        if ctx.meta is not None and ctx.meta.model_extra:  # pragma: no branch
            received_meta[0] = ctx.meta.model_extra.get("custom_field")

        async def work(task: ServerTaskContext) -> CallToolResult:
            await task.update_status("Working...")
            input_val = arguments.get("input", "default")
            result = CallToolResult(content=[TextContent(type="text", text=f"Processed: {input_val}")])
            work_completed.set()
            return result

        return await ctx.experimental.run_task(work)

    # Set up streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server() -> None:
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )

    async def run_client() -> None:
        async with ClientSession(server_to_client_receive, client_to_server_send) as client_session:
            # Initialize
            await client_session.initialize()

            # Call tool as task (with meta to test that code path)
            result = await client_session.experimental.call_tool_as_task(
                "simple_task",
                {"input": "hello"},
                meta={"custom_field": "test_value"},
            )

            # Should get CreateTaskResult
            task_id = result.task.taskId
            assert result.task.status == "working"

            # Wait for work to complete
            with anyio.fail_after(5):
                await work_completed.wait()

            # Poll until task status is completed
            with anyio.fail_after(5):
                while True:
                    task_status = await client_session.experimental.get_task(task_id)
                    if task_status.status == "completed":  # pragma: no branch
                        break

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)

    # Verify the meta was passed through correctly
    assert received_meta[0] == "test_value"


@pytest.mark.anyio
async def test_run_task_auto_fails_on_exception() -> None:
    """
    Test that run_task automatically fails the task when work raises.
    """
    server = Server("test-run-task-fail")
    server.experimental.enable_tasks()

    work_failed = Event()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="failing_task",
                description="A task that fails",
                inputSchema={"type": "object"},
                execution=ToolExecution(taskSupport=TASK_REQUIRED),
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult | CreateTaskResult:
        ctx = server.request_context
        ctx.experimental.validate_task_mode(TASK_REQUIRED)

        async def work(task: ServerTaskContext) -> CallToolResult:
            work_failed.set()
            raise RuntimeError("Something went wrong!")

        return await ctx.experimental.run_task(work)

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server() -> None:
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(),
        )

    async def run_client() -> None:
        async with ClientSession(server_to_client_receive, client_to_server_send) as client_session:
            await client_session.initialize()

            result = await client_session.experimental.call_tool_as_task("failing_task", {})
            task_id = result.task.taskId

            # Wait for work to fail
            with anyio.fail_after(5):
                await work_failed.wait()

            # Poll until task status is failed
            with anyio.fail_after(5):
                while True:
                    task_status = await client_session.experimental.get_task(task_id)
                    if task_status.status == "failed":  # pragma: no branch
                        break

            assert "Something went wrong" in (task_status.statusMessage or "")

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)


@pytest.mark.anyio
async def test_enable_tasks_auto_registers_handlers() -> None:
    """
    Test that enable_tasks() auto-registers get_task, list_tasks, cancel_task handlers.
    """
    server = Server("test-enable-tasks")

    # Before enable_tasks, no task capabilities
    caps_before = server.get_capabilities(NotificationOptions(), {})
    assert caps_before.tasks is None

    # Enable tasks
    server.experimental.enable_tasks()

    # After enable_tasks, should have task capabilities
    caps_after = server.get_capabilities(NotificationOptions(), {})
    assert caps_after.tasks is not None
    assert caps_after.tasks.list is not None
    assert caps_after.tasks.cancel is not None


@pytest.mark.anyio
async def test_enable_tasks_with_custom_store_and_queue() -> None:
    """Test that enable_tasks() uses provided store and queue instead of defaults."""
    server = Server("test-custom-store-queue")

    # Create custom store and queue
    custom_store = InMemoryTaskStore()
    custom_queue = InMemoryTaskMessageQueue()

    # Enable tasks with custom implementations
    task_support = server.experimental.enable_tasks(store=custom_store, queue=custom_queue)

    # Verify our custom implementations are used
    assert task_support.store is custom_store
    assert task_support.queue is custom_queue


@pytest.mark.anyio
async def test_enable_tasks_skips_default_handlers_when_custom_registered() -> None:
    """Test that enable_tasks() doesn't override already-registered handlers."""
    server = Server("test-custom-handlers")

    # Register custom handlers BEFORE enable_tasks (never called, just for registration)
    @server.experimental.get_task()
    async def custom_get_task(req: GetTaskRequest) -> GetTaskResult:
        raise NotImplementedError

    @server.experimental.get_task_result()
    async def custom_get_task_result(req: GetTaskPayloadRequest) -> GetTaskPayloadResult:
        raise NotImplementedError

    @server.experimental.list_tasks()
    async def custom_list_tasks(req: ListTasksRequest) -> ListTasksResult:
        raise NotImplementedError

    @server.experimental.cancel_task()
    async def custom_cancel_task(req: CancelTaskRequest) -> CancelTaskResult:
        raise NotImplementedError

    # Now enable tasks - should NOT override our custom handlers
    server.experimental.enable_tasks()

    # Verify our custom handlers are still registered (not replaced by defaults)
    # The handlers dict should contain our custom handlers
    assert GetTaskRequest in server.request_handlers
    assert GetTaskPayloadRequest in server.request_handlers
    assert ListTasksRequest in server.request_handlers
    assert CancelTaskRequest in server.request_handlers


@pytest.mark.anyio
async def test_run_task_without_enable_tasks_raises() -> None:
    """Test that run_task raises when enable_tasks() wasn't called."""
    experimental = Experimental(
        task_metadata=None,
        _client_capabilities=None,
        _session=None,
        _task_support=None,  # Not enabled
    )

    async def work(task: ServerTaskContext) -> CallToolResult:
        raise NotImplementedError

    with pytest.raises(RuntimeError, match="Task support not enabled"):
        await experimental.run_task(work)


@pytest.mark.anyio
async def test_task_support_task_group_before_run_raises() -> None:
    """Test that accessing task_group before run() raises RuntimeError."""
    task_support = TaskSupport.in_memory()

    with pytest.raises(RuntimeError, match="TaskSupport not running"):
        _ = task_support.task_group


@pytest.mark.anyio
async def test_run_task_without_session_raises() -> None:
    """Test that run_task raises when session is not available."""
    task_support = TaskSupport.in_memory()

    experimental = Experimental(
        task_metadata=None,
        _client_capabilities=None,
        _session=None,  # No session
        _task_support=task_support,
    )

    async def work(task: ServerTaskContext) -> CallToolResult:
        raise NotImplementedError

    with pytest.raises(RuntimeError, match="Session not available"):
        await experimental.run_task(work)


@pytest.mark.anyio
async def test_run_task_without_task_metadata_raises() -> None:
    """Test that run_task raises when request is not task-augmented."""
    task_support = TaskSupport.in_memory()
    mock_session = Mock()

    experimental = Experimental(
        task_metadata=None,  # Not a task-augmented request
        _client_capabilities=None,
        _session=mock_session,
        _task_support=task_support,
    )

    async def work(task: ServerTaskContext) -> CallToolResult:
        raise NotImplementedError

    with pytest.raises(RuntimeError, match="Request is not task-augmented"):
        await experimental.run_task(work)


@pytest.mark.anyio
async def test_run_task_with_model_immediate_response() -> None:
    """Test that run_task includes model_immediate_response in CreateTaskResult._meta."""
    server = Server("test-run-task-immediate")
    server.experimental.enable_tasks()

    work_completed = Event()
    immediate_response_text = "Processing your request..."

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="task_with_immediate",
                description="A task with immediate response",
                inputSchema={"type": "object"},
                execution=ToolExecution(taskSupport=TASK_REQUIRED),
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult | CreateTaskResult:
        ctx = server.request_context
        ctx.experimental.validate_task_mode(TASK_REQUIRED)

        async def work(task: ServerTaskContext) -> CallToolResult:
            work_completed.set()
            return CallToolResult(content=[TextContent(type="text", text="Done")])

        return await ctx.experimental.run_task(work, model_immediate_response=immediate_response_text)

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server() -> None:
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(),
        )

    async def run_client() -> None:
        async with ClientSession(server_to_client_receive, client_to_server_send) as client_session:
            await client_session.initialize()

            result = await client_session.experimental.call_tool_as_task("task_with_immediate", {})

            # Verify the immediate response is in _meta
            assert result.meta is not None
            assert "io.modelcontextprotocol/model-immediate-response" in result.meta
            assert result.meta["io.modelcontextprotocol/model-immediate-response"] == immediate_response_text

            with anyio.fail_after(5):
                await work_completed.wait()

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)


@pytest.mark.anyio
async def test_run_task_doesnt_complete_if_already_terminal() -> None:
    """Test that run_task doesn't auto-complete if work manually completed the task."""
    server = Server("test-already-complete")
    server.experimental.enable_tasks()

    work_completed = Event()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="manual_complete_task",
                description="A task that manually completes",
                inputSchema={"type": "object"},
                execution=ToolExecution(taskSupport=TASK_REQUIRED),
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult | CreateTaskResult:
        ctx = server.request_context
        ctx.experimental.validate_task_mode(TASK_REQUIRED)

        async def work(task: ServerTaskContext) -> CallToolResult:
            # Manually complete the task before returning
            manual_result = CallToolResult(content=[TextContent(type="text", text="Manually completed")])
            await task.complete(manual_result, notify=False)
            work_completed.set()
            # Return a different result - but it should be ignored since task is already terminal
            return CallToolResult(content=[TextContent(type="text", text="This should be ignored")])

        return await ctx.experimental.run_task(work)

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server() -> None:
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(),
        )

    async def run_client() -> None:
        async with ClientSession(server_to_client_receive, client_to_server_send) as client_session:
            await client_session.initialize()

            result = await client_session.experimental.call_tool_as_task("manual_complete_task", {})
            task_id = result.task.taskId

            with anyio.fail_after(5):
                await work_completed.wait()

            # Poll until task status is completed
            with anyio.fail_after(5):
                while True:
                    status = await client_session.experimental.get_task(task_id)
                    if status.status == "completed":  # pragma: no branch
                        break

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)


@pytest.mark.anyio
async def test_run_task_doesnt_fail_if_already_terminal() -> None:
    """Test that run_task doesn't auto-fail if work manually failed/cancelled the task."""
    server = Server("test-already-failed")
    server.experimental.enable_tasks()

    work_completed = Event()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="manual_cancel_task",
                description="A task that manually cancels then raises",
                inputSchema={"type": "object"},
                execution=ToolExecution(taskSupport=TASK_REQUIRED),
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult | CreateTaskResult:
        ctx = server.request_context
        ctx.experimental.validate_task_mode(TASK_REQUIRED)

        async def work(task: ServerTaskContext) -> CallToolResult:
            # Manually fail the task first
            await task.fail("Manually failed", notify=False)
            work_completed.set()
            # Then raise - but the auto-fail should be skipped since task is already terminal
            raise RuntimeError("This error should not change status")

        return await ctx.experimental.run_task(work)

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)

    async def run_server() -> None:
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(),
        )

    async def run_client() -> None:
        async with ClientSession(server_to_client_receive, client_to_server_send) as client_session:
            await client_session.initialize()

            result = await client_session.experimental.call_tool_as_task("manual_cancel_task", {})
            task_id = result.task.taskId

            with anyio.fail_after(5):
                await work_completed.wait()

            # Poll until task status is failed
            with anyio.fail_after(5):
                while True:
                    status = await client_session.experimental.get_task(task_id)
                    if status.status == "failed":  # pragma: no branch
                        break

            # Task should still be failed (from manual fail, not auto-fail from exception)
            assert status.statusMessage == "Manually failed"  # Not "This error should not change status"

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)
