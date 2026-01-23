"""Abstract base class for transport sessions."""

from abc import ABC, abstractmethod
from typing import Any


import mcp.types as types
from mcp.shared.message import SessionMessage


class ServerTransportSession(ABC):
    """Abstract base class for transport sessions."""
    @abstractmethod
    async def send_message(self, message: SessionMessage) -> None:
        """Send a raw session message."""
        raise NotImplementedError

    @abstractmethod
    async def send_log_message(
        self,
        level: types.LoggingLevel,
        data: Any,
        logger: str | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> None:
        """Send a log message notification."""
        raise NotImplementedError

    @abstractmethod
    async def send_resource_updated(self, uri: str) -> None:
        """Send a resource updated notification."""
        raise NotImplementedError

    @abstractmethod
    async def list_roots(self) -> types.ListRootsResult:
        """Send a roots/list request."""
        raise NotImplementedError

    @abstractmethod
    async def elicit(
        self,
        message: str,
        requested_schema: types.ElicitRequestedSchema,
        related_request_id: types.RequestId | None = None,
    ) -> types.ElicitResult:
        """Send an elicitation/create request."""
        raise NotImplementedError

    @abstractmethod
    async def elicit_form(
        self,
        message: str,
        requested_schema: types.ElicitRequestedSchema,
        related_request_id: types.RequestId | None = None,
    ) -> types.ElicitResult:
        """Send a form mode elicitation/create request."""
        raise NotImplementedError

    @abstractmethod
    async def elicit_url(
        self,
        message: str,
        url: str,
        elicitation_id: str,
        related_request_id: types.RequestId | None = None,
    ) -> types.ElicitResult:
        """Send a URL mode elicitation/create request."""
        raise NotImplementedError

    @abstractmethod
    async def send_ping(self) -> types.EmptyResult:
        """Send a ping request."""
        raise NotImplementedError

    @abstractmethod
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

    @abstractmethod
    async def send_resource_list_changed(self) -> None:
        """Send a resource list changed notification."""
        raise NotImplementedError

    @abstractmethod
    async def send_tool_list_changed(self) -> None:
        """Send a tool list changed notification."""
        raise NotImplementedError

    @abstractmethod
    async def send_prompt_list_changed(self) -> None:
        """Send a prompt list changed notification."""
        raise NotImplementedError
