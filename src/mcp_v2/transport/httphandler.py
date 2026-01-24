"""MCP V2 StreamableHTTPHandler - Framework-agnostic HTTP transport logic.

Manages sessions, creates sinks, spawns handler tasks, and decides
SSE vs JSON response format. No Starlette/Django/Flask dependency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import uuid4

import anyio
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream

from mcp_v2.runner import RunningServer
from mcp_v2.session import SessionInfo
from mcp_v2.transport.sink import ChannelSink, SinkEvent
from mcp_v2.types.json_rpc import JSONRPCErrorResponse, JSONRPCMessage, JSONRPCNotification, JSONRPCResponse

logger = logging.getLogger(__name__)


class _NoOpSink:
    """A sink that does nothing. Used for notifications which don't produce responses."""

    async def send_intermediate(self, message: JSONRPCMessage) -> None:
        pass

    async def send_result(self, response: JSONRPCResponse) -> None:
        pass

    async def close(self) -> None:
        pass


# --- Post result types ---


@dataclass
class AcceptedResponse:
    """Client responded to a server→client request. Just ack with 202."""


@dataclass
class JSONResult:
    """Handler completed without intermediate messages. Return as JSON."""

    body: JSONRPCResponse
    session_id: str


@dataclass
class SSEStream:
    """Handler is streaming. First event already available."""

    first_event: SinkEvent
    event_stream: MemoryObjectReceiveStream[SinkEvent]
    session_id: str


PostResult = AcceptedResponse | JSONResult | SSEStream


# --- HTTP Session ---


@dataclass
class HTTPSession:
    """Transport-level session state. Managed by StreamableHTTPHandler."""

    session_id: str = field(default_factory=lambda: uuid4().hex)
    session_info: SessionInfo | None = None


# --- Handler ---


class StreamableHTTPHandler:
    """Framework-agnostic StreamableHTTP logic.

    Testable without any HTTP framework — just call handle_post() with
    a session_id and a JSONRPCMessage.
    """

    def __init__(self, running: RunningServer, tg: TaskGroup) -> None:
        self._running = running
        self._tg = tg
        self._sessions: dict[str, HTTPSession] = {}

    async def handle_post(
        self,
        session_id: str | None,
        message: JSONRPCMessage,
    ) -> PostResult:
        """Handle a POST request. Returns a PostResult telling the framework what to respond with."""
        # Notifications don't produce responses — handle them immediately
        if isinstance(message, JSONRPCNotification):
            session = self._get_or_create_session(session_id)
            self._tg.start_soon(self._run_notification, message, session)
            return AcceptedResponse()

        # Get or create session
        session = self._get_or_create_session(session_id)

        # Create channel for handler → response
        send, recv = anyio.create_memory_object_stream[SinkEvent](16)
        sink = ChannelSink(send)

        # Run handler in background task
        self._tg.start_soon(self._run_handler, sink, message, session)

        # Read first event to decide response format
        try:
            first = await recv.receive()
        except anyio.EndOfStream:
            # Handler closed the sink without sending anything (shouldn't happen normally)
            return JSONResult(
                body=JSONRPCErrorResponse(id=0, error={"code": -32603, "message": "Internal error"}),  # type: ignore[arg-type]
                session_id=session.session_id,
            )

        if first.is_final:
            # Handler completed without sending intermediate messages → JSON
            async with recv:
                pass  # drain and close
            return JSONResult(body=first.message, session_id=session.session_id)  # type: ignore[arg-type]

        # Handler sent intermediate messages → SSE stream
        return SSEStream(
            first_event=first,
            event_stream=recv,
            session_id=session.session_id,
        )

    async def handle_delete(self, session_id: str) -> bool:
        """Handle a DELETE request (session termination)."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    async def _run_notification(
        self,
        message: JSONRPCMessage,
        session: HTTPSession,
    ) -> None:
        """Run a notification handler (no response needed)."""
        try:
            # Use a dummy sink that does nothing — notifications don't produce responses
            sink = _NoOpSink()
            await self._running.handle_message(sink, message, session=session.session_info)
        except Exception:
            logger.exception("Notification handler error")

    async def _run_handler(
        self,
        sink: ChannelSink,
        message: JSONRPCMessage,
        session: HTTPSession,
    ) -> None:
        """Run the handler and close the sink when done."""
        try:
            result = await self._running.handle_message(
                sink,
                message,
                session=session.session_info,
            )
            # If this was an init handshake, store the session info
            if isinstance(result, SessionInfo):
                session.session_info = result
        except BaseException:
            logger.exception("Handler error")
            await sink.close()

    def _get_or_create_session(self, session_id: str | None) -> HTTPSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        session = HTTPSession()
        self._sessions[session.session_id] = session
        return session
