from typing import Any, TypeVar

from typing_extensions import Protocol, runtime_checkable

from mcp import types
from mcp.shared.session import ProgressFnT
from mcp.types._types import RequestParamsMeta

ClientSessionT_contra = TypeVar("ClientSessionT_contra", bound="BaseClientSession", contravariant=True)


@runtime_checkable
class BaseClientSession(Protocol):
    """Protocol defining the interface for MCP client sessions.

    This protocol specifies all methods that a client session must implement,
    irrespective of the transport used. Implementations satisfy this protocol
    through structural subtyping — no inheritance required.
    """

    # Methods from AbstractBaseSession (must be explicitly declared in Protocol)
    async def send_request(
        self,
        request: types.ClientRequest,
        result_type: type,
        request_read_timeout_seconds: float | None = None,
        metadata: Any = None,
        progress_callback: ProgressFnT | None = None,
    ) -> Any: ...

    async def send_notification(
        self,
        notification: types.ClientNotification,
        related_request_id: Any = None,
    ) -> None: ...

    async def send_progress_notification(
        self,
        progress_token: types.ProgressToken,
        progress: float,
        total: float | None = None,
        message: str | None = None,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> None: ...

    # Client-specific methods
    async def initialize(self) -> types.InitializeResult: ...

    async def send_ping(self, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult: ...

    async def list_resources(
        self, *, params: types.PaginatedRequestParams | None = None
    ) -> types.ListResourcesResult: ...

    async def list_resource_templates(
        self, *, params: types.PaginatedRequestParams | None = None
    ) -> types.ListResourceTemplatesResult: ...

    async def read_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.ReadResourceResult: ...

    async def subscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult: ...

    async def unsubscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult: ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> types.CallToolResult: ...

    async def list_prompts(self, *, params: types.PaginatedRequestParams | None = None) -> types.ListPromptsResult: ...

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> types.GetPromptResult: ...

    async def list_tools(self, *, params: types.PaginatedRequestParams | None = None) -> types.ListToolsResult: ...

    # Missing methods added per review
    async def complete(
        self,
        ref: types.ResourceTemplateReference | types.PromptReference,
        argument: dict[str, str],
        context_arguments: dict[str, str] | None = None,
    ) -> types.CompleteResult: ...

    async def set_logging_level(
        self,
        level: types.LoggingLevel,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> types.EmptyResult: ...

    async def send_roots_list_changed(self) -> None: ...
