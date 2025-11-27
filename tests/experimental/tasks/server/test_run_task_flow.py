"""
Tests for the simplified task API: enable_tasks() + run_task()

This tests the recommended user flow:
1. server.experimental.enable_tasks() - one-line setup
2. ctx.experimental.run_task(work) - spawns work, returns CreateTaskResult
3. work function uses ServerTaskContext for elicit/create_message

These are integration tests that verify the complete flow works end-to-end.
"""

from typing import Any

import anyio
import pytest
from anyio import Event

from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.server.lowlevel import NotificationOptions
from mcp.shared.message import SessionMessage
from mcp.types import (
    TASK_REQUIRED,
    CallToolResult,
    CreateTaskResult,
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

    # Track when work completes
    work_completed = Event()

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

            # Call tool as task
            result = await client_session.experimental.call_tool_as_task(
                "simple_task",
                {"input": "hello"},
            )

            # Should get CreateTaskResult
            task_id = result.task.taskId
            assert result.task.status == "working"

            # Wait for work to complete
            with anyio.fail_after(5):
                await work_completed.wait()

            # Small delay to let task state update
            await anyio.sleep(0.1)

            # Poll task status
            task_status = await client_session.experimental.get_task(task_id)
            assert task_status.status == "completed"

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)


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

            await anyio.sleep(0.1)

            # Task should be failed
            task_status = await client_session.experimental.get_task(task_id)
            assert task_status.status == "failed"
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
