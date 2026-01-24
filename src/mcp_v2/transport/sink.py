"""MCP V2 Transport Sinks - ResponseSink implementations."""

from __future__ import annotations

from dataclasses import dataclass

import anyio
from anyio.streams.memory import MemoryObjectSendStream

from mcp_v2.types.json_rpc import JSONRPCMessage, JSONRPCResponse


@dataclass
class SinkEvent:
    """An event produced by a ResponseSink for the transport layer to consume."""

    message: JSONRPCMessage
    event_id: str | None = None
    is_final: bool = False


class ChannelSink:
    """ResponseSink that writes events to a memory channel.

    Used by the HTTP transport. The HTTP handler reads from the other end
    of the channel to decide SSE vs JSON response format.
    """

    def __init__(self, send_stream: MemoryObjectSendStream[SinkEvent]) -> None:
        self._send = send_stream
        self._closed = False

    async def send_intermediate(self, message: JSONRPCMessage) -> None:
        """Send an intermediate message (notification or server→client request)."""
        if self._closed:
            return
        await self._send.send(SinkEvent(message=message))

    async def send_result(self, response: JSONRPCResponse) -> None:
        """Send the final result and close the channel."""
        if self._closed:
            return
        await self._send.send(SinkEvent(message=response, is_final=True))
        self._closed = True
        await self._send.aclose()

    async def close(self) -> None:
        """Close the channel without sending a result (e.g., on handler error)."""
        if self._closed:
            return
        self._closed = True
        with anyio.CancelScope(shield=True):
            await self._send.aclose()
