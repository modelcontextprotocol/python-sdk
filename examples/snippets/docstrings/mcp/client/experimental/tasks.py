"""Companion examples for src/mcp/client/experimental/tasks.py docstrings."""

from __future__ import annotations

import anyio

from mcp.client.session import ClientSession
from mcp.types import CallToolResult


async def module_overview(session: ClientSession) -> None:
    # region module_overview
    # Call a tool as a task
    result = await session.experimental.call_tool_as_task("tool_name", {"arg": "value"})
    task_id = result.task.task_id

    # Get task status
    status = await session.experimental.get_task(task_id)

    # Get task result when complete
    if status.status == "completed":
        result = await session.experimental.get_task_result(task_id, CallToolResult)

    # List all tasks
    tasks = await session.experimental.list_tasks()

    # Cancel a task
    await session.experimental.cancel_task(task_id)
    # endregion module_overview


async def ExperimentalClientFeatures_call_tool_as_task_usage(session: ClientSession) -> None:
    # region ExperimentalClientFeatures_call_tool_as_task_usage
    # Create task
    result = await session.experimental.call_tool_as_task("long_running_tool", {"input": "data"})
    task_id = result.task.task_id

    # Poll for completion
    while True:
        status = await session.experimental.get_task(task_id)
        if status.status == "completed":
            break
        await anyio.sleep(0.5)

    # Get result
    final = await session.experimental.get_task_result(task_id, CallToolResult)
    # endregion ExperimentalClientFeatures_call_tool_as_task_usage


async def ExperimentalClientFeatures_poll_task_usage(session: ClientSession, task_id: str) -> None:
    # region ExperimentalClientFeatures_poll_task_usage
    async for status in session.experimental.poll_task(task_id):
        print(f"Status: {status.status}")
        if status.status == "input_required":
            # Handle elicitation request via tasks/result
            pass

    # Task is now terminal, get the result
    result = await session.experimental.get_task_result(task_id, CallToolResult)
    # endregion ExperimentalClientFeatures_poll_task_usage
