"""Companion examples for src/mcp/client/session.py docstrings."""

from __future__ import annotations

from mcp.client.session import ClientSession
from mcp.types import CallToolResult


async def ClientSession_experimental_usage(session: ClientSession, task_id: str) -> None:
    # region ClientSession_experimental_usage
    status = await session.experimental.get_task(task_id)
    result = await session.experimental.get_task_result(task_id, CallToolResult)
    # endregion ClientSession_experimental_usage
