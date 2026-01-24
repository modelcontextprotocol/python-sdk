"""MCP V2 Context - RequestContext and ResponseSink protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from mcp_v2.session import SessionInfo
from mcp_v2.types.json_rpc import (
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCResponse,
    RequestId,
)


@runtime_checkable
class ResponseSink(Protocol):
    """Transport-specific sink for outgoing messages during request processing.

    One per incoming request. The transport provides different implementations:
    - ChannelSink (HTTP): writes events to a channel, HTTP layer decides SSE vs JSON
    - DirectSink (stdio): writes directly to the transport
    - StatelessSink: buffers or raises ContinuationNeeded
    """

    async def send_intermediate(self, message: JSONRPCMessage) -> None:
        """Send a notification or server→client request during processing."""
        ...

    async def send_result(self, response: JSONRPCResponse) -> None:
        """Send the final result. After this, the sink is done."""
        ...

    async def close(self) -> None:
        """Ensure the sink is closed (e.g., on handler error)."""
        ...


@dataclass
class RequestContext:
    """What handlers receive. Provides server→client communication.

    The implementation of communication varies by execution mode (stateful vs stateless),
    but handlers don't need to know which mode they're running in.
    """

    server_state: Any
    session: SessionInfo | None
    request_id: RequestId
    _sink: ResponseSink

    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a notification to the client during request processing.

        In HTTP: this forces the response to be an SSE stream.
        In stdio: this writes directly to the transport.
        """
        notification = JSONRPCNotification(method=method, params=params)
        await self._sink.send_intermediate(notification)
