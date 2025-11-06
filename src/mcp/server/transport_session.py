"""Abstract base class for transport sessions."""

import abc
from typing import Any

from anyio.streams.memory import MemoryObjectReceiveStream
from pydantic import AnyUrl

import mcp.types as types
from mcp.server.session import ServerRequestResponder


class TransportSession(abc.ABC):
    """Abstract base class for transport sessions."""

    @property
    @abc.abstractmethod
    def client_params(self) -> types.InitializeRequestParams | None:
        """Client initialization parameters."""
        raise NotImplementedError

    @abc.abstractmethod
    def check_client_capability(self, capability: types.ClientCapabilities) -> bool:
        """Check if the client supports a specific capability."""
        raise NotImplementedError

    @abc.abstractmethod
    async def send_log_message(
        self,
        level: types.LoggingLevel,
        data: Any,
        logger: str | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> None:
        """Send a log message notification."""
        raise NotImplementedError

    @abc.abstractmethod
    async def send_resource_updated(self, uri: AnyUrl) -> None:
        """Send a resource updated notification."""
        raise NotImplementedError

    @abc.abstractmethod
    async def create_message(
        self,
        messages: list[types.SamplingMessage],
        *,
        max_tokens: int,
        system_prompt: str | None = None,
        include_context: types.IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: types.ModelPreferences | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> types.CreateMessageResult:
        """Send a sampling/create_message request."""
        raise NotImplementedError

    @abc.abstractmethod
    async def list_roots(self) -> types.ListRootsResult:
        """Send a roots/list request."""
        raise NotImplementedError

    @abc.abstractmethod
    async def elicit(
        self,
        message: str,
        requestedSchema: types.ElicitRequestedSchema,
        related_request_id: types.RequestId | None = None,
    ) -> types.ElicitResult:
        """Send an elicitation/create request."""
        raise NotImplementedError

    @abc.abstractmethod
    async def send_ping(self) -> types.EmptyResult:
        """Send a ping request."""
        raise NotImplementedError

    @abc.abstractmethod
    async def send_progress_notification(
        self,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
        related_request_id: str | None = None,
    ) -> None:
        """Send a progress notification."""
        raise NotImplementedError

    @abc.abstractmethod
    async def send_resource_list_changed(self) -> None:
        """Send a resource list changed notification."""
        raise NotImplementedError

    @abc.abstractmethod
    async def send_tool_list_changed(self) -> None:
        """Send a tool list changed notification."""
        raise NotImplementedError

    @abc.abstractmethod
    async def send_prompt_list_changed(self) -> None:
        """Send a prompt list changed notification."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def incoming_messages(
        self,
    ) -> MemoryObjectReceiveStream[ServerRequestResponder]:
        """Incoming messages stream."""
        raise NotImplementedError
