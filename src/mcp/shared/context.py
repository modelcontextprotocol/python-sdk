from dataclasses import dataclass, field
from typing import Any, Generic

from typing_extensions import TypeVar

from mcp.shared.exceptions import McpError
from mcp.shared.session import BaseSession
from mcp.types import (
    METHOD_NOT_FOUND,
    TASK_FORBIDDEN,
    TASK_REQUIRED,
    ClientCapabilities,
    ErrorData,
    RequestId,
    RequestParams,
    TaskExecutionMode,
    TaskMetadata,
    Tool,
)

SessionT = TypeVar("SessionT", bound=BaseSession[Any, Any, Any, Any, Any])
LifespanContextT = TypeVar("LifespanContextT")
RequestT = TypeVar("RequestT", default=Any)


@dataclass
class Experimental:
    """
    Experimental features context for task-augmented requests.

    Provides helpers for validating task execution compatibility.
    """

    task_metadata: TaskMetadata | None = None
    _client_capabilities: ClientCapabilities | None = field(default=None, repr=False)

    @property
    def is_task(self) -> bool:
        """Check if this request is task-augmented."""
        return self.task_metadata is not None

    @property
    def client_supports_tasks(self) -> bool:
        """Check if the client declared task support."""
        if self._client_capabilities is None:
            return False
        return self._client_capabilities.tasks is not None

    def validate_task_mode(
        self,
        tool_task_mode: TaskExecutionMode | None,
        *,
        raise_error: bool = True,
    ) -> ErrorData | None:
        """
        Validate that the request is compatible with the tool's task execution mode.

        Per MCP spec:
        - "required": Clients MUST invoke as task. Server returns -32601 if not.
        - "forbidden" (or None): Clients MUST NOT invoke as task. Server returns -32601 if they do.
        - "optional": Either is acceptable.

        Args:
            tool_task_mode: The tool's execution.taskSupport value
                ("forbidden", "optional", "required", or None)
            raise_error: If True, raises McpError on validation failure. If False, returns ErrorData.

        Returns:
            None if valid, ErrorData if invalid and raise_error=False

        Raises:
            McpError: If invalid and raise_error=True
        """

        mode = tool_task_mode or TASK_FORBIDDEN

        error: ErrorData | None = None

        if mode == TASK_REQUIRED and not self.is_task:
            error = ErrorData(
                code=METHOD_NOT_FOUND,
                message="This tool requires task-augmented invocation",
            )
        elif mode == TASK_FORBIDDEN and self.is_task:
            error = ErrorData(
                code=METHOD_NOT_FOUND,
                message="This tool does not support task-augmented invocation",
            )

        if error is not None and raise_error:
            raise McpError(error)

        return error

    def validate_for_tool(
        self,
        tool: Tool,
        *,
        raise_error: bool = True,
    ) -> ErrorData | None:
        """
        Validate that the request is compatible with the given tool.

        Convenience wrapper around validate_task_mode that extracts the mode from a Tool.

        Args:
            tool: The Tool definition
            raise_error: If True, raises McpError on validation failure.

        Returns:
            None if valid, ErrorData if invalid and raise_error=False
        """
        mode = tool.execution.taskSupport if tool.execution else None
        return self.validate_task_mode(mode, raise_error=raise_error)

    def can_use_tool(self, tool_task_mode: TaskExecutionMode | None) -> bool:
        """
        Check if this client can use a tool with the given task mode.

        Useful for filtering tool lists or providing warnings.
        Returns False if tool requires "required" but client doesn't support tasks.

        Args:
            tool_task_mode: The tool's execution.taskSupport value

        Returns:
            True if the client can use this tool, False otherwise
        """
        mode = tool_task_mode or TASK_FORBIDDEN
        if mode == TASK_REQUIRED and not self.client_supports_tasks:
            return False
        return True


@dataclass
class RequestContext(Generic[SessionT, LifespanContextT, RequestT]):
    request_id: RequestId
    meta: RequestParams.Meta | None
    session: SessionT
    lifespan_context: LifespanContextT
    experimental: Experimental = field(default_factory=Experimental)
    request: RequestT | None = None
