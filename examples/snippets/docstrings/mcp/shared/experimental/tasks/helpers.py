"""Companion examples for src/mcp/shared/experimental/tasks/helpers.py docstrings."""

from __future__ import annotations

from typing import Any

from mcp.shared.experimental.tasks.helpers import cancel_task
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.types import CancelTaskRequestParams, CancelTaskResult


def cancel_task_usage(store: TaskStore) -> None:
    # region cancel_task_usage
    async def handle_cancel(ctx: Any, params: CancelTaskRequestParams) -> CancelTaskResult:
        return await cancel_task(store, params.task_id)

    # endregion cancel_task_usage
