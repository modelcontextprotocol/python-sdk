"""Companion examples for src/mcp/server/experimental/request_context.py docstrings."""

from __future__ import annotations

from typing import Any

from mcp.server.context import ServerRequestContext
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.types import CallToolRequestParams, CallToolResult, CreateTaskResult, TextContent


def Experimental_run_task_usage() -> None:
    # region Experimental_run_task_usage
    async def handle_tool(
        ctx: ServerRequestContext[Any, Any],
        params: CallToolRequestParams,
    ) -> CreateTaskResult:
        async def work(task: ServerTaskContext) -> CallToolResult:
            result = await task.elicit(
                message="Are you sure?",
                requested_schema={"type": "object", "properties": {"confirm": {"type": "boolean"}}},
            )
            if result.action == "accept" and result.content:
                confirmed = result.content.get("confirm", False)
            else:
                confirmed = False
            return CallToolResult(content=[TextContent(text="Done" if confirmed else "Cancelled")])

        return await ctx.experimental.run_task(work)

    # endregion Experimental_run_task_usage
