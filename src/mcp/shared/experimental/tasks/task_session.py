"""
TaskSession - Task-aware session wrapper for MCP.

When a handler is executing a task-augmented request, it should use TaskSession
instead of ServerSession directly. TaskSession transparently handles:

1. Enqueuing requests (like elicitation) instead of sending directly
2. Auto-managing task status (working <-> input_required)
3. Routing responses back to the original caller

This implements the message queue pattern from the MCP Tasks spec.
"""

import uuid
from typing import TYPE_CHECKING, Any

import anyio

from mcp.shared.exceptions import McpError
from mcp.shared.experimental.tasks.message_queue import QueuedMessage, TaskMessageQueue
from mcp.shared.experimental.tasks.resolver import Resolver
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.types import (
    ClientCapabilities,
    CreateMessageRequestParams,
    CreateMessageResult,
    ElicitationCapability,
    ElicitRequestedSchema,
    ElicitRequestParams,
    ElicitResult,
    ErrorData,
    IncludeContext,
    JSONRPCNotification,
    JSONRPCRequest,
    LoggingMessageNotification,
    LoggingMessageNotificationParams,
    ModelPreferences,
    RelatedTaskMetadata,
    RequestId,
    SamplingCapability,
    SamplingMessage,
    ServerNotification,
)

# Metadata key for associating requests with a task (per MCP spec)
RELATED_TASK_METADATA_KEY = "io.modelcontextprotocol/related-task"

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

    @property
    def task_id(self) -> str:
        """The task identifier."""
        return self._task_id

    def _next_request_id(self) -> RequestId:
        """
        Generate a unique request ID for queued requests.

        Uses UUIDs to avoid collision with integer IDs from BaseSession.send_request().
        The MCP spec allows request IDs to be strings or integers.
        """
        return f"task-{self._task_id}-{uuid.uuid4().hex[:8]}"

    def _check_elicitation_capability(self) -> None:
        """Check if the client supports elicitation."""
        if not self._session.check_client_capability(ClientCapabilities(elicitation=ElicitationCapability())):
            raise McpError(
                ErrorData(
                    code=-32600,  # INVALID_REQUEST - client doesn't support this
                    message="Client does not support elicitation capability",
                )
            )

    def _check_sampling_capability(self) -> None:
        """Check if the client supports sampling."""
        if not self._session.check_client_capability(ClientCapabilities(sampling=SamplingCapability())):
            raise McpError(
                ErrorData(
                    code=-32600,  # INVALID_REQUEST - client doesn't support this
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
        3. Enqueues the elicitation request
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
        # Check capability first
        self._check_elicitation_capability()

        # Update status to input_required
        await self._store.update_task(self._task_id, status="input_required")

        # Create the elicitation request with related-task metadata
        request_id = self._next_request_id()

        # Build params with _meta containing related-task info
        params = ElicitRequestParams(
            message=message,
            requestedSchema=requestedSchema,
        )
        params_data = params.model_dump(by_alias=True, mode="json", exclude_none=True)

        # Add related-task metadata to _meta
        related_task = RelatedTaskMetadata(taskId=self._task_id)
        if "_meta" not in params_data:
            params_data["_meta"] = {}
        params_data["_meta"][RELATED_TASK_METADATA_KEY] = related_task.model_dump(
            by_alias=True, mode="json", exclude_none=True
        )

        request_data: dict[str, Any] = {
            "method": "elicitation/create",
            "params": params_data,
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
        3. Enqueues the sampling request
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
        # Check capability first
        self._check_sampling_capability()

        # Update status to input_required
        await self._store.update_task(self._task_id, status="input_required")

        # Create the sampling request with related-task metadata
        request_id = self._next_request_id()

        # Build params with _meta containing related-task info
        params = CreateMessageRequestParams(
            messages=messages,
            maxTokens=max_tokens,
            systemPrompt=system_prompt,
            includeContext=include_context,
            temperature=temperature,
            stopSequences=stop_sequences,
            metadata=metadata,
            modelPreferences=model_preferences,
        )
        params_data = params.model_dump(by_alias=True, mode="json", exclude_none=True)

        # Add related-task metadata to _meta
        related_task = RelatedTaskMetadata(taskId=self._task_id)
        if "_meta" not in params_data:
            params_data["_meta"] = {}
        params_data["_meta"][RELATED_TASK_METADATA_KEY] = related_task.model_dump(
            by_alias=True, mode="json", exclude_none=True
        )

        request_data: dict[str, Any] = {
            "method": "sampling/createMessage",
            "params": params_data,
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
            return CreateMessageResult.model_validate(response_data)
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
