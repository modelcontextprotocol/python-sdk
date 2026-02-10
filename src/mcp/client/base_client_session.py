from abc import abstractmethod
from typing import Any, TypeVar

from mcp import types
from mcp.shared.session import CommonBaseSession, ProgressFnT
from mcp.types._types import RequestParamsMeta

ClientSessionT_contra = TypeVar("ClientSessionT_contra", bound="BaseClientSession", contravariant=True)


class BaseClientSession(
    CommonBaseSession[
        types.ClientRequest,
        types.ClientNotification,
        types.ClientResult,
        types.ServerRequest,
        types.ServerNotification,
    ]
):
    """Base class for client transport sessions.

    The class provides all the methods that a client session should implement,
    irrespective of the transport used.
    """

    @abstractmethod
    async def initialize(self) -> types.InitializeResult:
        """Initialize the client session."""
        raise NotImplementedError

    @abstractmethod
    async def send_ping(self, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
        """Send a ping request."""
        raise NotImplementedError

    @abstractmethod
    async def list_resources(self, *, params: types.PaginatedRequestParams | None = None) -> types.ListResourcesResult:
        """Send a resources/list request.

        Args:
            params: Full pagination parameters including cursor and any future fields
        """
        raise NotImplementedError

    @abstractmethod
    async def list_resource_templates(
        self, *, params: types.PaginatedRequestParams | None = None
    ) -> types.ListResourceTemplatesResult:
        """Send a resources/templates/list request.

        Args:
            params: Full pagination parameters including cursor and any future fields
        """
        raise NotImplementedError

    @abstractmethod
    async def read_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.ReadResourceResult:
        """Send a resources/read request."""
        raise NotImplementedError

    @abstractmethod
    async def subscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
        """Send a resources/subscribe request."""
        raise NotImplementedError

    @abstractmethod
    async def unsubscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
        """Send a resources/unsubscribe request."""
        raise NotImplementedError

    @abstractmethod
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> types.CallToolResult:
        """Send a tools/call request with optional progress callback support."""
        raise NotImplementedError

    @abstractmethod
    async def list_prompts(self, *, params: types.PaginatedRequestParams | None = None) -> types.ListPromptsResult:
        """Send a prompts/list request.

        Args:
            params: Full pagination parameters including cursor and any future fields
        """
        raise NotImplementedError

    @abstractmethod
    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> types.GetPromptResult:
        """Send a prompts/get request."""
        raise NotImplementedError

    @abstractmethod
    async def list_tools(self, *, params: types.PaginatedRequestParams | None = None) -> types.ListToolsResult:
        """Send a tools/list request.

        Args:
            params: Full pagination parameters including cursor and any future fields
        """
        raise NotImplementedError

    @abstractmethod
    async def send_roots_list_changed(self) -> None:  # pragma: no cover
        """Send a roots/list_changed notification."""
        raise NotImplementedError
