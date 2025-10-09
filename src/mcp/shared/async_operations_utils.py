import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp import types
from mcp.shared.message import SessionMessage

if TYPE_CHECKING:
    # Avoid circular import with mcp.server.lowlevel.Server
    from mcp.shared.context import SerializableRequestContext


@dataclass
class ClientAsyncOperation:
    """Minimal operation tracking for client-side use."""

    token: str
    tool_name: str
    created_at: float
    keep_alive: int

    @property
    def is_expired(self) -> bool:
        """Check if operation has expired based on keepAlive."""
        return time.time() > (self.created_at + self.keep_alive * 2)  # Give some buffer before expiration


@dataclass
class ServerAsyncOperation:
    """Represents an async tool operation."""

    token: str
    tool_name: str
    arguments: dict[str, Any]
    status: types.AsyncOperationStatus
    created_at: float
    keep_alive: int
    resolved_at: float | None = None
    session_id: str | None = None
    result: types.CallToolResult | None = None
    error: str | None = None

    @property
    def is_expired(self) -> bool:
        """Check if operation has expired based on keepAlive."""
        if not self.resolved_at:
            return False
        if self.status in ("completed", "failed", "canceled"):
            return time.time() > (self.resolved_at + self.keep_alive)
        return False

    @property
    def is_terminal(self) -> bool:
        """Check if operation is in a terminal state."""
        return self.status in ("completed", "failed", "canceled", "unknown")


@dataclass
class ToolExecutorParameters:
    tool_name: str
    arguments: dict[str, Any]
    request_context: "SerializableRequestContext"
    server_read: MemoryObjectReceiveStream[SessionMessage | Exception]
    server_write: MemoryObjectSendStream[SessionMessage]
