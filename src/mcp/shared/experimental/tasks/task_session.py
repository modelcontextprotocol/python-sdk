"""
TaskSession - Task-aware session wrapper for MCP.

When a handler is executing a task-augmented request, it should use TaskSession
instead of ServerSession directly. TaskSession transparently handles:

1. Enqueuing requests (like elicitation) instead of sending directly
2. Auto-managing task status (working <-> input_required)
3. Routing responses back to the original caller

This implements the message queue pattern from the MCP Tasks spec.
"""

from typing import TYPE_CHECKING, Any

import anyio

from mcp.shared.experimental.tasks.message_queue import QueuedMessage, TaskMessageQueue
from mcp.shared.experimental.tasks.resolver import Resolver
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.types import (
    ElicitRequestedSchema,
    ElicitRequestParams,
    ElicitResult,
    JSONRPCNotification,
    JSONRPCRequest,
    LoggingMessageNotification,
    LoggingMessageNotificationParams,
    ServerNotification,
)

if TYPE_CHECKING:
    from mcp.server.session import ServerSession


class TaskSession:
    """
    Task-aware session wrapper.

    This wraps a ServerSession and provides methods that automatically handle
    the task message queue pattern. When you call `elicit()` on a TaskSession,
    the request is enqueued instead of sent directly. It will be delivered
    to the client via the `tasks/result` endpoint.

    Example:
        async def my_tool_handler(ctx: RequestContext) -> CallToolResult:
            if ctx.experimental.is_task:
                # Create task-aware session
                task_session = TaskSession(
                    session=ctx.session,
                    task_id=task_id,
                    store=task_store,
                    queue=message_queue,
                )

                # This enqueues instead of sending directly
                result = await task_session.elicit(
                    message="What is your preference?",
                    requestedSchema={"type": "string"}
                )
            else:
                # Normal elicitation
                result = await ctx.session.elicit(...)
    """

    def __init__(
        self,
        session: "ServerSession",
        task_id: str,
        store: TaskStore,
        queue: TaskMessageQueue,
    ):
        self._session = session
        self._task_id = task_id
        self._store = store
        self._queue = queue
        self._request_id_counter = 0

    @property
    def task_id(self) -> str:
        """The task identifier."""
        return self._task_id

    def _next_request_id(self) -> int:
        """Generate a unique request ID for queued requests."""
        self._request_id_counter += 1
        return self._request_id_counter

    async def elicit(
        self,
        message: str,
        requestedSchema: ElicitRequestedSchema,
    ) -> ElicitResult:
        """
        Send an elicitation request via the task message queue.

        This method:
        1. Updates task status to "input_required"
        2. Enqueues the elicitation request
        3. Waits for the response (delivered via tasks/result round-trip)
        4. Updates task status back to "working"
        5. Returns the result

        Args:
            message: The message to present to the user
            requestedSchema: Schema defining the expected response structure

        Returns:
            The client's response
        """
        # Update status to input_required
        await self._store.update_task(self._task_id, status="input_required")

        # Create the elicitation request
        request_id = self._next_request_id()
        request_data: dict[str, Any] = {
            "method": "elicitation/create",
            "params": ElicitRequestParams(
                message=message,
                requestedSchema=requestedSchema,
            ).model_dump(by_alias=True, mode="json", exclude_none=True),
        }

        jsonrpc_request = JSONRPCRequest(
            jsonrpc="2.0",
            id=request_id,
            **request_data,
        )

        # Create a resolver to receive the response
        resolver: Resolver[dict[str, Any]] = Resolver()

        # Enqueue the request
        queued_message = QueuedMessage(
            type="request",
            message=jsonrpc_request,
            resolver=resolver,
            original_request_id=request_id,
        )
        await self._queue.enqueue(self._task_id, queued_message)

        try:
            # Wait for the response
            response_data = await resolver.wait()

            # Update status back to working
            await self._store.update_task(self._task_id, status="working")

            # Parse the result
            return ElicitResult.model_validate(response_data)
        except anyio.get_cancelled_exc_class():
            # If cancelled, update status back to working before re-raising
            await self._store.update_task(self._task_id, status="working")
            raise

    async def send_log_message(
        self,
        level: str,
        data: Any,
        logger: str | None = None,
    ) -> None:
        """
        Send a log message notification via the task message queue.

        Unlike requests, notifications don't expect a response, so they're
        just enqueued for delivery.

        Args:
            level: The log level
            data: The log data
            logger: Optional logger name
        """
        notification = ServerNotification(
            LoggingMessageNotification(
                params=LoggingMessageNotificationParams(
                    level=level,  # type: ignore[arg-type]
                    data=data,
                    logger=logger,
                ),
            )
        )

        jsonrpc_notification = JSONRPCNotification(
            jsonrpc="2.0",
            **notification.model_dump(by_alias=True, mode="json", exclude_none=True),
        )

        queued_message = QueuedMessage(
            type="notification",
            message=jsonrpc_notification,
        )
        await self._queue.enqueue(self._task_id, queued_message)

    # Passthrough methods that don't need queueing

    def check_client_capability(self, capability: Any) -> bool:
        """Check if the client supports a specific capability."""
        return self._session.check_client_capability(capability)

    @property
    def client_params(self) -> Any:
        """Get client initialization parameters."""
        return self._session.client_params
