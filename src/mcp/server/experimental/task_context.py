"""
ServerTaskContext - Server-integrated task context with elicitation and sampling.

This wraps the pure TaskContext and adds server-specific functionality:
- Elicitation (task.elicit())
- Sampling (task.create_message())
- Status notifications
"""

from typing import Any

import anyio

from mcp.server.experimental.task_result_handler import TaskResultHandler
from mcp.server.session import ServerSession
from mcp.shared.exceptions import McpError
from mcp.shared.experimental.tasks.context import TaskContext
from mcp.shared.experimental.tasks.helpers import create_task_state
from mcp.shared.experimental.tasks.message_queue import QueuedMessage, TaskMessageQueue
from mcp.shared.experimental.tasks.resolver import Resolver
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.types import (
    INVALID_REQUEST,
    TASK_STATUS_INPUT_REQUIRED,
    TASK_STATUS_WORKING,
    ClientCapabilities,
    CreateMessageResult,
    ElicitationCapability,
    ElicitRequestedSchema,
    ElicitResult,
    ErrorData,
    IncludeContext,
    ModelPreferences,
    RequestId,
    Result,
    SamplingCapability,
    SamplingMessage,
    ServerNotification,
    Task,
    TaskMetadata,
    TaskStatusNotification,
    TaskStatusNotificationParams,
)


class ServerTaskContext:
    """
    Server-integrated task context with elicitation and sampling.

    This wraps a pure TaskContext and adds server-specific functionality:
    - elicit() for sending elicitation requests to the client
    - create_message() for sampling requests
    - Status notifications via the session

    Example:
        async def my_task_work(task: ServerTaskContext) -> CallToolResult:
            await task.update_status("Starting...")

            result = await task.elicit(
                message="Continue?",
                requestedSchema={"type": "object", "properties": {"ok": {"type": "boolean"}}}
            )

            if result.content.get("ok"):
                return CallToolResult(content=[TextContent(text="Done!")])
            else:
                return CallToolResult(content=[TextContent(text="Cancelled")])
    """

    def __init__(
        self,
        *,
        task: Task | None = None,
        task_id: str | None = None,
        store: TaskStore,
        session: ServerSession,
        queue: TaskMessageQueue,
        handler: TaskResultHandler | None = None,
    ):
        """
        Create a ServerTaskContext.

        Args:
            task: The Task object (provide either task or task_id)
            task_id: The task ID to look up (provide either task or task_id)
            store: The task store
            session: The server session
            queue: The message queue for elicitation/sampling
            handler: The result handler for response routing (required for elicit/create_message)
        """
        if task is None and task_id is None:
            raise ValueError("Must provide either task or task_id")
        if task is not None and task_id is not None:
            raise ValueError("Provide either task or task_id, not both")

        # If task_id provided, create a minimal task object
        # This is for backwards compatibility with tests that pass task_id
        if task is None:
            task = create_task_state(TaskMetadata(ttl=None), task_id=task_id)

        self._ctx = TaskContext(task=task, store=store)
        self._session = session
        self._queue = queue
        self._handler = handler
        self._store = store

    # Delegate pure properties to inner context

    @property
    def task_id(self) -> str:
        """The task identifier."""
        return self._ctx.task_id

    @property
    def task(self) -> Task:
        """The current task state."""
        return self._ctx.task

    @property
    def is_cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._ctx.is_cancelled

    def request_cancellation(self) -> None:
        """Request cancellation of this task."""
        self._ctx.request_cancellation()

    # Enhanced methods with notifications

    async def update_status(self, message: str, *, notify: bool = True) -> None:
        """
        Update the task's status message.

        Args:
            message: The new status message
            notify: Whether to send a notification to the client
        """
        await self._ctx.update_status(message)
        if notify:
            await self._send_notification()

    async def complete(self, result: Result, *, notify: bool = True) -> None:
        """
        Mark the task as completed with the given result.

        Args:
            result: The task result
            notify: Whether to send a notification to the client
        """
        await self._ctx.complete(result)
        if notify:
            await self._send_notification()

    async def fail(self, error: str, *, notify: bool = True) -> None:
        """
        Mark the task as failed with an error message.

        Args:
            error: The error message
            notify: Whether to send a notification to the client
        """
        await self._ctx.fail(error)
        if notify:
            await self._send_notification()

    async def _send_notification(self) -> None:
        """Send a task status notification to the client."""
        task = self._ctx.task
        await self._session.send_notification(
            ServerNotification(
                TaskStatusNotification(
                    params=TaskStatusNotificationParams(
                        taskId=task.taskId,
                        status=task.status,
                        statusMessage=task.statusMessage,
                        createdAt=task.createdAt,
                        lastUpdatedAt=task.lastUpdatedAt,
                        ttl=task.ttl,
                        pollInterval=task.pollInterval,
                    )
                )
            )
        )

    # Server-specific methods: elicitation and sampling

    def _check_elicitation_capability(self) -> None:
        """Check if the client supports elicitation."""
        if not self._session.check_client_capability(ClientCapabilities(elicitation=ElicitationCapability())):
            raise McpError(
                ErrorData(
                    code=INVALID_REQUEST,
                    message="Client does not support elicitation capability",
                )
            )

    def _check_sampling_capability(self) -> None:
        """Check if the client supports sampling."""
        if not self._session.check_client_capability(ClientCapabilities(sampling=SamplingCapability())):
            raise McpError(
                ErrorData(
                    code=INVALID_REQUEST,
                    message="Client does not support sampling capability",
                )
            )

    async def elicit(
        self,
        message: str,
        requestedSchema: ElicitRequestedSchema,
    ) -> ElicitResult:
        """
        Send an elicitation request via the task message queue.

        This method:
        1. Checks client capability
        2. Updates task status to "input_required"
        3. Queues the elicitation request
        4. Waits for the response (delivered via tasks/result round-trip)
        5. Updates task status back to "working"
        6. Returns the result

        Args:
            message: The message to present to the user
            requestedSchema: Schema defining the expected response structure

        Returns:
            The client's response

        Raises:
            McpError: If client doesn't support elicitation capability
        """
        self._check_elicitation_capability()

        if self._handler is None:
            raise RuntimeError("handler is required for elicit(). Pass handler= to ServerTaskContext.")

        # Update status to input_required
        await self._store.update_task(self.task_id, status=TASK_STATUS_INPUT_REQUIRED)

        # Build the request using session's helper
        request = self._session._build_elicit_request(  # pyright: ignore[reportPrivateUsage]
            message=message,
            requestedSchema=requestedSchema,
            task_id=self.task_id,
        )
        request_id: RequestId = request.id

        # Create resolver and register with handler for response routing
        resolver: Resolver[dict[str, Any]] = Resolver()
        self._handler._pending_requests[request_id] = resolver  # pyright: ignore[reportPrivateUsage]

        # Queue the request
        queued = QueuedMessage(
            type="request",
            message=request,
            resolver=resolver,
            original_request_id=request_id,
        )
        await self._queue.enqueue(self.task_id, queued)

        try:
            # Wait for response (routed back via TaskResultHandler)
            response_data = await resolver.wait()
            await self._store.update_task(self.task_id, status=TASK_STATUS_WORKING)
            return ElicitResult.model_validate(response_data)
        except anyio.get_cancelled_exc_class():
            await self._store.update_task(self.task_id, status=TASK_STATUS_WORKING)
            raise

    async def create_message(
        self,
        messages: list[SamplingMessage],
        *,
        max_tokens: int,
        system_prompt: str | None = None,
        include_context: IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: ModelPreferences | None = None,
    ) -> CreateMessageResult:
        """
        Send a sampling request via the task message queue.

        This method:
        1. Checks client capability
        2. Updates task status to "input_required"
        3. Queues the sampling request
        4. Waits for the response (delivered via tasks/result round-trip)
        5. Updates task status back to "working"
        6. Returns the result

        Args:
            messages: The conversation messages for sampling
            max_tokens: Maximum tokens in the response
            system_prompt: Optional system prompt
            include_context: Context inclusion strategy
            temperature: Sampling temperature
            stop_sequences: Stop sequences
            metadata: Additional metadata
            model_preferences: Model selection preferences

        Returns:
            The sampling result from the client

        Raises:
            McpError: If client doesn't support sampling capability
        """
        self._check_sampling_capability()

        if self._handler is None:
            raise RuntimeError("handler is required for create_message(). Pass handler= to ServerTaskContext.")

        # Update status to input_required
        await self._store.update_task(self.task_id, status=TASK_STATUS_INPUT_REQUIRED)

        # Build the request using session's helper
        request = self._session._build_create_message_request(  # pyright: ignore[reportPrivateUsage]
            messages=messages,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            include_context=include_context,
            temperature=temperature,
            stop_sequences=stop_sequences,
            metadata=metadata,
            model_preferences=model_preferences,
            task_id=self.task_id,
        )
        request_id: RequestId = request.id

        # Create resolver and register with handler for response routing
        resolver: Resolver[dict[str, Any]] = Resolver()
        self._handler._pending_requests[request_id] = resolver  # pyright: ignore[reportPrivateUsage]

        # Queue the request
        queued = QueuedMessage(
            type="request",
            message=request,
            resolver=resolver,
            original_request_id=request_id,
        )
        await self._queue.enqueue(self.task_id, queued)

        try:
            # Wait for response (routed back via TaskResultHandler)
            response_data = await resolver.wait()
            await self._store.update_task(self.task_id, status=TASK_STATUS_WORKING)
            return CreateMessageResult.model_validate(response_data)
        except anyio.get_cancelled_exc_class():
            await self._store.update_task(self.task_id, status=TASK_STATUS_WORKING)
            raise
