"""Tests for the simplified task API: enable_tasks() + run_task()

This tests the recommended user flow:
1. server.experimental.enable_tasks() - one-line setup
2. ctx.experimental.run_task(work) - spawns work, returns CreateTaskResult
3. work function uses ServerTaskContext for elicit/create_message

These are integration tests that verify the complete flow works end-to-end.
"""

from unittest.mock import Mock

import anyio
import pytest
from anyio import Event

from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.server.experimental.request_context import Experimental
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.server.experimental.task_support import TaskSupport
from mcp.server.lowlevel import NotificationOptions
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.experimental.tasks.message_queue import InMemoryTaskMessageQueue
from mcp.types import (
    TASK_REQUIRED,
    CallToolRequestParams,
    CallToolResult,
    CreateTaskResult,
    GetTaskRequestParams,
    GetTaskResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
    ToolExecution,
)

pytestmark = pytest.mark.anyio


async def _handle_list_tools_simple_task(
    ctx: ServerRequestContext, params: PaginatedRequestParams | None
) -> ListToolsResult:
    return ListToolsResult(
        tools=[
            Tool(
                name="simple_task",
                description="A simple task",
                input_schema={"type": "object", "properties": {"input": {"type": "string"}}},
                execution=ToolExecution(task_support=TASK_REQUIRED),
            )
        ]
    )


async def test_run_task_basic_flow() -> None:
    """Test the basic run_task flow without elicitation."""
    work_completed = Event()
    received_meta: list[str | None] = [None]

    async def handle_call_tool(
        ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult | CreateTaskResult:
        ctx.experimental.validate_task_mode(TASK_REQUIRED)

        if ctx.meta is not None:  # pragma: no branch
            received_meta[0] = ctx.meta.get("custom_field")

        async def work(task: ServerTaskContext) -> CallToolResult:
            await task.update_status("Working...")
            input_val = (params.arguments or {}).get("input", "default")
            result = CallToolResult(content=[TextContent(type="text", text=f"Processed: {input_val}")])
            work_completed.set()
            return result

        return await ctx.experimental.run_task(work)

    server = Server(
        "test-run-task",
        on_list_tools=_handle_list_tools_simple_task,
        on_call_tool=handle_call_tool,
    )
    server.experimental.enable_tasks()

    async with Client(server) as client:
        result = await client.session.experimental.call_tool_as_task(
            "simple_task",
            {"input": "hello"},
            meta={"custom_field": "test_value"},
        )

        task_id = result.task.task_id
        assert result.task.status == "working"

        with anyio.fail_after(5):
            await work_completed.wait()

        with anyio.fail_after(5):
            while True:
                task_status = await client.session.experimental.get_task(task_id)
                if task_status.status == "completed":  # pragma: no branch
                    break

    assert received_meta[0] == "test_value"


async def test_run_task_auto_fails_on_exception() -> None:
    """Test that run_task automatically fails the task when work raises."""
    work_failed = Event()

    async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(
                    name="failing_task",
                    description="A task that fails",
                    input_schema={"type": "object"},
                    execution=ToolExecution(task_support=TASK_REQUIRED),
                )
            ]
        )

    async def handle_call_tool(
        ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult | CreateTaskResult:
        ctx.experimental.validate_task_mode(TASK_REQUIRED)

        async def work(task: ServerTaskContext) -> CallToolResult:
            work_failed.set()
            raise RuntimeError("Something went wrong!")

        return await ctx.experimental.run_task(work)

    server = Server(
        "test-run-task-fail",
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )
    server.experimental.enable_tasks()

    async with Client(server) as client:
        result = await client.session.experimental.call_tool_as_task("failing_task", {})
        task_id = result.task.task_id

        with anyio.fail_after(5):
            await work_failed.wait()

        with anyio.fail_after(5):
            while True:
                task_status = await client.session.experimental.get_task(task_id)
                if task_status.status == "failed":  # pragma: no branch
                    break

        assert "Something went wrong" in (task_status.status_message or "")


async def test_enable_tasks_auto_registers_handlers() -> None:
    """Test that enable_tasks() auto-registers get_task, list_tasks, cancel_task handlers."""
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
    assert caps_after.tasks.requests is not None
    assert caps_after.tasks.requests.tools is not None
    assert caps_after.tasks.requests.tools.call is not None


async def test_enable_tasks_with_custom_store_and_queue() -> None:
    """Test that enable_tasks() uses provided store and queue instead of defaults."""
    server = Server("test-custom-store-queue")

    custom_store = InMemoryTaskStore()
    custom_queue = InMemoryTaskMessageQueue()

    task_support = server.experimental.enable_tasks(store=custom_store, queue=custom_queue)

    assert task_support.store is custom_store
    assert task_support.queue is custom_queue


async def test_enable_tasks_skips_default_handlers_when_custom_registered() -> None:
    """Test that enable_tasks() doesn't override already-registered handlers."""
    server = Server("test-custom-handlers")

    # Register custom handlers via enable_tasks kwargs
    async def custom_get_task(ctx: ServerRequestContext, params: GetTaskRequestParams) -> GetTaskResult:
        raise NotImplementedError

    server.experimental.enable_tasks(on_get_task=custom_get_task)

    # Verify handler is registered
    assert server._has_handler("tasks/get")
    assert server._has_handler("tasks/list")
    assert server._has_handler("tasks/cancel")
    assert server._has_handler("tasks/result")


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


async def test_task_support_task_group_before_run_raises() -> None:
    """Test that accessing task_group before run() raises RuntimeError."""
    task_support = TaskSupport.in_memory()

    with pytest.raises(RuntimeError, match="TaskSupport not running"):
        _ = task_support.task_group


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


async def test_run_task_with_model_immediate_response() -> None:
    """Test that run_task includes model_immediate_response in CreateTaskResult._meta."""
    work_completed = Event()
    immediate_response_text = "Processing your request..."

    async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(
                    name="task_with_immediate",
                    description="A task with immediate response",
                    input_schema={"type": "object"},
                    execution=ToolExecution(task_support=TASK_REQUIRED),
                )
            ]
        )

    async def handle_call_tool(
        ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult | CreateTaskResult:
        ctx.experimental.validate_task_mode(TASK_REQUIRED)

        async def work(task: ServerTaskContext) -> CallToolResult:
            work_completed.set()
            return CallToolResult(content=[TextContent(type="text", text="Done")])

        return await ctx.experimental.run_task(work, model_immediate_response=immediate_response_text)

    server = Server(
        "test-run-task-immediate",
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )
    server.experimental.enable_tasks()

    async with Client(server) as client:
        result = await client.session.experimental.call_tool_as_task("task_with_immediate", {})

        assert result.meta is not None
        assert "io.modelcontextprotocol/model-immediate-response" in result.meta
        assert result.meta["io.modelcontextprotocol/model-immediate-response"] == immediate_response_text

        with anyio.fail_after(5):
            await work_completed.wait()


async def test_run_task_doesnt_complete_if_already_terminal() -> None:
    """Test that run_task doesn't auto-complete if work manually completed the task."""
    work_completed = Event()

    async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(
                    name="manual_complete_task",
                    description="A task that manually completes",
                    input_schema={"type": "object"},
                    execution=ToolExecution(task_support=TASK_REQUIRED),
                )
            ]
        )

    async def handle_call_tool(
        ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult | CreateTaskResult:
        ctx.experimental.validate_task_mode(TASK_REQUIRED)

        async def work(task: ServerTaskContext) -> CallToolResult:
            manual_result = CallToolResult(content=[TextContent(type="text", text="Manually completed")])
            await task.complete(manual_result, notify=False)
            work_completed.set()
            return CallToolResult(content=[TextContent(type="text", text="This should be ignored")])

        return await ctx.experimental.run_task(work)

    server = Server(
        "test-already-complete",
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )
    server.experimental.enable_tasks()

    async with Client(server) as client:
        result = await client.session.experimental.call_tool_as_task("manual_complete_task", {})
        task_id = result.task.task_id

        with anyio.fail_after(5):
            await work_completed.wait()

        with anyio.fail_after(5):
            while True:
                status = await client.session.experimental.get_task(task_id)
                if status.status == "completed":  # pragma: no branch
                    break


async def test_run_task_doesnt_fail_if_already_terminal() -> None:
    """Test that run_task doesn't auto-fail if work manually failed/cancelled the task."""
    work_completed = Event()

    async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(
                    name="manual_cancel_task",
                    description="A task that manually cancels then raises",
                    input_schema={"type": "object"},
                    execution=ToolExecution(task_support=TASK_REQUIRED),
                )
            ]
        )

    async def handle_call_tool(
        ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult | CreateTaskResult:
        ctx.experimental.validate_task_mode(TASK_REQUIRED)

        async def work(task: ServerTaskContext) -> CallToolResult:
            await task.fail("Manually failed", notify=False)
            work_completed.set()
            raise RuntimeError("This error should not change status")

        return await ctx.experimental.run_task(work)

    server = Server(
        "test-already-failed",
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )
    server.experimental.enable_tasks()

    async with Client(server) as client:
        result = await client.session.experimental.call_tool_as_task("manual_cancel_task", {})
        task_id = result.task.task_id

        with anyio.fail_after(5):
            await work_completed.wait()

        with anyio.fail_after(5):
            while True:
                status = await client.session.experimental.get_task(task_id)
                if status.status == "failed":  # pragma: no branch
                    break

        assert status.status_message == "Manually failed"
