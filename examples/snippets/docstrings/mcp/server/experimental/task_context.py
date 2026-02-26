"""Companion examples for src/mcp/server/experimental/task_context.py docstrings."""

from __future__ import annotations

from mcp.server.experimental.task_context import ServerTaskContext
from mcp.types import CallToolResult, TextContent


async def ServerTaskContext_usage(task: ServerTaskContext) -> None:
    # region ServerTaskContext_usage
    async def my_task_work(task: ServerTaskContext) -> CallToolResult:
        await task.update_status("Starting...")

        result = await task.elicit(
            message="Continue?",
            requested_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        )

        if result.action == "accept" and result.content and result.content.get("ok"):
            return CallToolResult(content=[TextContent(text="Done!")])
        else:
            return CallToolResult(content=[TextContent(text="Cancelled")])

    # endregion ServerTaskContext_usage
