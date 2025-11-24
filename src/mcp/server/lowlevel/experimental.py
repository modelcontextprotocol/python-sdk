"""Experimental handlers for the low-level MCP server.

WARNING: These APIs are experimental and may change without notice.
"""

import logging
from collections.abc import Awaitable, Callable

from mcp.server.lowlevel.func_inspection import create_call_wrapper
from mcp.types import (
    CancelTaskRequest,
    CancelTaskResult,
    GetTaskPayloadRequest,
    GetTaskPayloadResult,
    GetTaskRequest,
    GetTaskResult,
    ListTasksRequest,
    ListTasksResult,
    ServerCapabilities,
    ServerResult,
    ServerTasksCapability,
    ServerTasksRequestsCapability,
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
        request_handlers: dict[type, Callable[..., Awaitable[ServerResult]]],
        notification_handlers: dict[type, Callable[..., Awaitable[None]]],
    ):
        self._request_handlers = request_handlers
        self._notification_handlers = notification_handlers

    def update_capabilities(self, capabilities: ServerCapabilities) -> None:
        capabilities.tasks = ServerTasksCapability()
        if ListTasksRequest in self._request_handlers:
            capabilities.tasks.list = TasksListCapability()
        if CancelTaskRequest in self._request_handlers:
            capabilities.tasks.cancel = TasksCancelCapability()

        capabilities.tasks.requests = ServerTasksRequestsCapability(
            tools=TasksToolsCapability()
        )  # assuming always supported for now

    def list_tasks(
        self,
    ) -> Callable[
        [Callable[[ListTasksRequest], Awaitable[ListTasksResult]]],
        Callable[[ListTasksRequest], Awaitable[ListTasksResult]],
    ]:
        """Register a handler for listing tasks.

        WARNING: This API is experimental and may change without notice.
        """

        def decorator(
            func: Callable[[ListTasksRequest], Awaitable[ListTasksResult]],
        ) -> Callable[[ListTasksRequest], Awaitable[ListTasksResult]]:
            logger.debug("Registering handler for ListTasksRequest")
            wrapper = create_call_wrapper(func, ListTasksRequest)

            async def handler(req: ListTasksRequest) -> ServerResult:
                result = await wrapper(req)
                return ServerResult(result)

            self._request_handlers[ListTasksRequest] = handler
            return func

        return decorator

    def get_task(
        self,
    ) -> Callable[
        [Callable[[GetTaskRequest], Awaitable[GetTaskResult]]], Callable[[GetTaskRequest], Awaitable[GetTaskResult]]
    ]:
        """Register a handler for getting task status.

        WARNING: This API is experimental and may change without notice.
        """

        def decorator(
            func: Callable[[GetTaskRequest], Awaitable[GetTaskResult]],
        ) -> Callable[[GetTaskRequest], Awaitable[GetTaskResult]]:
            logger.debug("Registering handler for GetTaskRequest")
            wrapper = create_call_wrapper(func, GetTaskRequest)

            async def handler(req: GetTaskRequest) -> ServerResult:
                result = await wrapper(req)
                return ServerResult(result)

            self._request_handlers[GetTaskRequest] = handler
            return func

        return decorator

    def get_task_result(
        self,
    ) -> Callable[
        [Callable[[GetTaskPayloadRequest], Awaitable[GetTaskPayloadResult]]],
        Callable[[GetTaskPayloadRequest], Awaitable[GetTaskPayloadResult]],
    ]:
        """Register a handler for getting task results/payload.

        WARNING: This API is experimental and may change without notice.
        """

        def decorator(
            func: Callable[[GetTaskPayloadRequest], Awaitable[GetTaskPayloadResult]],
        ) -> Callable[[GetTaskPayloadRequest], Awaitable[GetTaskPayloadResult]]:
            logger.debug("Registering handler for GetTaskPayloadRequest")
            wrapper = create_call_wrapper(func, GetTaskPayloadRequest)

            async def handler(req: GetTaskPayloadRequest) -> ServerResult:
                result = await wrapper(req)
                return ServerResult(result)

            self._request_handlers[GetTaskPayloadRequest] = handler
            return func

        return decorator

    def cancel_task(
        self,
    ) -> Callable[
        [Callable[[CancelTaskRequest], Awaitable[CancelTaskResult]]],
        Callable[[CancelTaskRequest], Awaitable[CancelTaskResult]],
    ]:
        """Register a handler for cancelling tasks.

        WARNING: This API is experimental and may change without notice.
        """

        def decorator(
            func: Callable[[CancelTaskRequest], Awaitable[CancelTaskResult]],
        ) -> Callable[[CancelTaskRequest], Awaitable[CancelTaskResult]]:
            logger.debug("Registering handler for CancelTaskRequest")
            wrapper = create_call_wrapper(func, CancelTaskRequest)

            async def handler(req: CancelTaskRequest) -> ServerResult:
                result = await wrapper(req)
                return ServerResult(result)

            self._request_handlers[CancelTaskRequest] = handler
            return func

        return decorator
