"""Experimental handlers for the low-level MCP server.

WARNING: These APIs are experimental and may change without notice.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.context import ServerRequestContext
from mcp.server.experimental.task_support import TaskSupport
from mcp.shared.exceptions import MCPError
from mcp.shared.experimental.tasks.helpers import cancel_task
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.experimental.tasks.message_queue import InMemoryTaskMessageQueue, TaskMessageQueue
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.types import (
    INVALID_PARAMS,
    CancelTaskRequestParams,
    CancelTaskResult,
    GetTaskPayloadRequest,
    GetTaskPayloadRequestParams,
    GetTaskPayloadResult,
    GetTaskRequestParams,
    GetTaskResult,
    ListTasksResult,
    PaginatedRequestParams,
    ServerCapabilities,
    ServerTasksCapability,
    ServerTasksRequestsCapability,
    TasksCallCapability,
    TasksCancelCapability,
    TasksListCapability,
    TasksToolsCapability,
)

logger = logging.getLogger(__name__)


class ExperimentalHandlers:
    """Experimental request/notification handlers.

    WARNING: These APIs are experimental and may change without notice.
    """

    def __init__(
        self,
        add_request_handler: Callable[[str, Callable[[ServerRequestContext[Any, Any], Any], Awaitable[Any]]], None],
        has_handler: Callable[[str], bool],
    ) -> None:
        self._add_request_handler = add_request_handler
        self._has_handler = has_handler
        self._task_support: TaskSupport | None = None

    @property
    def task_support(self) -> TaskSupport | None:
        """Get the task support configuration, if enabled."""
        return self._task_support

    def update_capabilities(self, capabilities: ServerCapabilities) -> None:
        # Only add tasks capability if handlers are registered
        if not any(self._has_handler(method) for method in ["tasks/get", "tasks/list", "tasks/cancel", "tasks/result"]):
            return

        capabilities.tasks = ServerTasksCapability()
        if self._has_handler("tasks/list"):
            capabilities.tasks.list = TasksListCapability()
        if self._has_handler("tasks/cancel"):
            capabilities.tasks.cancel = TasksCancelCapability()

        capabilities.tasks.requests = ServerTasksRequestsCapability(
            tools=TasksToolsCapability(call=TasksCallCapability())
        )  # assuming always supported for now

    def enable_tasks(
        self,
        store: TaskStore | None = None,
        queue: TaskMessageQueue | None = None,
        *,
        on_get_task: Callable[[ServerRequestContext[Any, Any], GetTaskRequestParams], Awaitable[GetTaskResult]]
        | None = None,
        on_task_result: Callable[
            [ServerRequestContext[Any, Any], GetTaskPayloadRequestParams], Awaitable[GetTaskPayloadResult]
        ]
        | None = None,
        on_list_tasks: Callable[
            [ServerRequestContext[Any, Any], PaginatedRequestParams | None], Awaitable[ListTasksResult]
        ]
        | None = None,
        on_cancel_task: Callable[
            [ServerRequestContext[Any, Any], CancelTaskRequestParams], Awaitable[CancelTaskResult]
        ]
        | None = None,
    ) -> TaskSupport:
        """Enable experimental task support.

        This sets up the task infrastructure and registers handlers for
        tasks/get, tasks/result, tasks/list, and tasks/cancel. Custom handlers
        can be provided via the on_* kwargs; any not provided will use defaults.

        Args:
            store: Custom TaskStore implementation (defaults to InMemoryTaskStore)
            queue: Custom TaskMessageQueue implementation (defaults to InMemoryTaskMessageQueue)
            on_get_task: Custom handler for tasks/get
            on_task_result: Custom handler for tasks/result
            on_list_tasks: Custom handler for tasks/list
            on_cancel_task: Custom handler for tasks/cancel

        Returns:
            The TaskSupport configuration object

        Example:
            # Simple in-memory setup
            server.experimental.enable_tasks()

            # Custom store/queue for distributed systems
            server.experimental.enable_tasks(
                store=RedisTaskStore(redis_url),
                queue=RedisTaskMessageQueue(redis_url),
            )

        WARNING: This API is experimental and may change without notice.
        """
        if store is None:
            store = InMemoryTaskStore()
        if queue is None:
            queue = InMemoryTaskMessageQueue()

        self._task_support = TaskSupport(store=store, queue=queue)

        # Register user-provided handlers
        if on_get_task is not None:
            self._add_request_handler("tasks/get", on_get_task)
        if on_task_result is not None:
            self._add_request_handler("tasks/result", on_task_result)
        if on_list_tasks is not None:
            self._add_request_handler("tasks/list", on_list_tasks)
        if on_cancel_task is not None:
            self._add_request_handler("tasks/cancel", on_cancel_task)

        # Fill in defaults for any not provided
        if not self._has_handler("tasks/get"):

            async def _default_get_task(
                ctx: ServerRequestContext[Any, Any], params: GetTaskRequestParams
            ) -> GetTaskResult:
                task = await self._task_support.store.get_task(params.task_id)
                if task is None:
                    raise MCPError(code=INVALID_PARAMS, message=f"Task not found: {params.task_id}")
                return GetTaskResult(
                    task_id=task.task_id,
                    status=task.status,
                    status_message=task.status_message,
                    created_at=task.created_at,
                    last_updated_at=task.last_updated_at,
                    ttl=task.ttl,
                    poll_interval=task.poll_interval,
                )

            self._add_request_handler("tasks/get", _default_get_task)

        if not self._has_handler("tasks/result"):

            async def _default_get_task_result(
                ctx: ServerRequestContext[Any, Any], params: GetTaskPayloadRequestParams
            ) -> GetTaskPayloadResult:
                assert ctx.request_id is not None
                req = GetTaskPayloadRequest(params=params)
                result = await self._task_support.handler.handle(req, ctx.session, ctx.request_id)
                return result

            self._add_request_handler("tasks/result", _default_get_task_result)

        if not self._has_handler("tasks/list"):

            async def _default_list_tasks(
                ctx: ServerRequestContext[Any, Any], params: PaginatedRequestParams | None
            ) -> ListTasksResult:
                cursor = params.cursor if params else None
                tasks, next_cursor = await self._task_support.store.list_tasks(cursor)
                return ListTasksResult(tasks=tasks, next_cursor=next_cursor)

            self._add_request_handler("tasks/list", _default_list_tasks)

        if not self._has_handler("tasks/cancel"):

            async def _default_cancel_task(
                ctx: ServerRequestContext[Any, Any], params: CancelTaskRequestParams
            ) -> CancelTaskResult:
                result = await cancel_task(self._task_support.store, params.task_id)
                return result

            self._add_request_handler("tasks/cancel", _default_cancel_task)
