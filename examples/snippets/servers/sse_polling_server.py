"""
SSE Polling Example Server

Demonstrates server-initiated SSE stream disconnection for polling behavior.

Key features:
- retryInterval: Tells clients how long to wait before reconnecting (2 seconds)
- eventStore: Persists events for replay after reconnection
- close_sse_stream(): Gracefully disconnects clients mid-operation

The server creates a `long-task` tool that:
1. Sends progress notifications at 25%, 50%, 75%, 100%
2. At 50%, closes the SSE stream to trigger client reconnection
3. Continues processing - events are stored and replayed on reconnect

Run:
    uv run examples/snippets/servers/sse_polling_server.py
"""

import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

import anyio
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http import EventCallback, EventId, EventMessage, EventStore, StreamId
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

# Configure logging to show progress
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class InMemoryEventStore(EventStore):
    """Simple in-memory event store for demonstrating SSE polling resumability."""

    def __init__(self) -> None:
        self._events: dict[StreamId, list[tuple[EventId, types.JSONRPCMessage]]] = {}
        self._event_index: dict[EventId, tuple[StreamId, types.JSONRPCMessage]] = {}
        self._counter = 0

    async def store_event(self, stream_id: StreamId, message: types.JSONRPCMessage) -> EventId:
        event_id = f"evt-{self._counter}"
        self._counter += 1

        if stream_id not in self._events:
            self._events[stream_id] = []
        self._events[stream_id].append((event_id, message))
        self._event_index[event_id] = (stream_id, message)

        logger.debug(f"Stored event {event_id} for stream {stream_id}")
        return event_id

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        if last_event_id not in self._event_index:
            logger.warning(f"Event {last_event_id} not found")
            return None

        stream_id, _ = self._event_index[last_event_id]
        events = self._events.get(stream_id, [])

        # Find events after last_event_id
        found = False
        for event_id, message in events:
            if found:
                await send_callback(EventMessage(message, event_id))
                logger.info(f"Replayed event {event_id}")
            elif event_id == last_event_id:
                found = True

        return stream_id


def create_app() -> Starlette:
    """Create the Starlette application with SSE polling example server."""
    app = Server("sse-polling-example")

    @app.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        if name != "long-task":
            raise ValueError(f"Unknown tool: {name}")

        ctx = app.request_context
        request_id = ctx.request_id

        logger.info(f"[{request_id}] Starting long-task...")

        # Progress 25%
        await ctx.session.send_log_message(
            level="info",
            data="Progress: 25% - Starting work...",
            related_request_id=request_id,
        )
        logger.info(f"[{request_id}] Progress: 25%")
        await anyio.sleep(1)

        # Progress 50%
        await ctx.session.send_log_message(
            level="info",
            data="Progress: 50% - Halfway there...",
            related_request_id=request_id,
        )
        logger.info(f"[{request_id}] Progress: 50%")
        await anyio.sleep(1)

        # Server-initiated disconnect - client will reconnect
        # Use the close_sse_stream callback if available
        # This is None if not on streamable HTTP transport or no event store configured
        if ctx.close_sse_stream:
            logger.info(f"[{request_id}] Closing SSE stream to trigger polling reconnect...")
            await ctx.close_sse_stream(retry_interval=2000)  # 2 seconds

        # Wait a bit for client to reconnect
        await anyio.sleep(0.5)

        # Progress 75% - sent while client was disconnected, stored for replay
        await ctx.session.send_log_message(
            level="info",
            data="Progress: 75% - Almost done (sent while disconnected)...",
            related_request_id=request_id,
        )
        logger.info(f"[{request_id}] Progress: 75% (client may be disconnected)")
        await anyio.sleep(0.5)

        # Progress 100%
        await ctx.session.send_log_message(
            level="info",
            data="Progress: 100% - Complete!",
            related_request_id=request_id,
        )
        logger.info(f"[{request_id}] Progress: 100%")

        return [types.TextContent(type="text", text="Long task completed successfully!")]

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="long-task",
                description=(
                    "A long-running task that demonstrates server-initiated SSE disconnect. "
                    "The server closes the connection at 50% progress, and the client "
                    "automatically reconnects to receive the remaining updates."
                ),
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    # Create event store and session manager
    event_store = InMemoryEventStore()
    session_manager = StreamableHTTPSessionManager(
        app=app,
        event_store=event_store,
        # Tell clients to reconnect after 2 seconds
        retry_interval=2000,
    )

    async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            logger.info("SSE Polling Example Server started on http://localhost:3001/mcp")
            yield
            logger.info("Server shutting down...")

    return Starlette(
        debug=True,
        routes=[Mount("/mcp", app=handle_mcp)],
        lifespan=lifespan,
    )


if __name__ == "__main__":
    import uvicorn

    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=3001)
