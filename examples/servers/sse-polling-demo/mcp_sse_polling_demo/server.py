"""
SSE Polling Demo Server

Demonstrates the SSE polling pattern with close_sse_stream() for long-running tasks.

Features demonstrated:
- Priming events (automatic with EventStore)
- Server-initiated stream close via close_sse_stream callback
- Client auto-reconnect with Last-Event-ID
- Progress notifications during long-running tasks

Run with:
    uv run mcp-sse-polling-demo --port 3000
"""

import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

import anyio
import click
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from .event_store import InMemoryEventStore

logger = logging.getLogger(__name__)


@click.command()
@click.option("--port", default=3000, help="Port to listen on")
@click.option(
    "--log-level",
    default="INFO",
    help="Logging level (DEBUG, INFO, WARNING, ERROR)",
)
@click.option(
    "--retry-interval",
    default=100,
    help="SSE retry interval in milliseconds (sent to client)",
)
def main(port: int, log_level: str, retry_interval: int) -> int:
    """Run the SSE Polling Demo server."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create the lowlevel server
    app = Server("sse-polling-demo")

    @app.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        """Handle tool calls."""
        ctx = app.request_context

        if name == "process_batch":
            items = arguments.get("items", 10)
            checkpoint_every = arguments.get("checkpoint_every", 3)

            if items < 1 or items > 100:
                return [types.TextContent(type="text", text="Error: items must be between 1 and 100")]
            if checkpoint_every < 1 or checkpoint_every > 20:
                return [types.TextContent(type="text", text="Error: checkpoint_every must be between 1 and 20")]

            await ctx.session.send_log_message(
                level="info",
                data=f"Starting batch processing of {items} items...",
                logger="process_batch",
                related_request_id=ctx.request_id,
            )

            for i in range(1, items + 1):
                # Simulate work
                await anyio.sleep(0.5)

                # Report progress
                await ctx.session.send_log_message(
                    level="info",
                    data=f"[{i}/{items}] Processing item {i}",
                    logger="process_batch",
                    related_request_id=ctx.request_id,
                )

                # Checkpoint: close stream to trigger client reconnect
                if i % checkpoint_every == 0 and i < items:
                    await ctx.session.send_log_message(
                        level="info",
                        data=f"Checkpoint at item {i} - closing SSE stream for polling",
                        logger="process_batch",
                        related_request_id=ctx.request_id,
                    )
                    if ctx.close_sse_stream:
                        logger.info(f"Closing SSE stream at checkpoint {i}")
                        await ctx.close_sse_stream()
                    # Wait for client to reconnect (must be > retry_interval of 100ms)
                    await anyio.sleep(0.2)

            return [
                types.TextContent(
                    type="text",
                    text=f"Successfully processed {items} items with checkpoints every {checkpoint_every} items",
                )
            ]

        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        """List available tools."""
        return [
            types.Tool(
                name="process_batch",
                description=(
                    "Process a batch of items with periodic checkpoints. "
                    "Demonstrates SSE polling where server closes stream periodically."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "integer",
                            "description": "Number of items to process (1-100)",
                            "default": 10,
                        },
                        "checkpoint_every": {
                            "type": "integer",
                            "description": "Close stream after this many items (1-20)",
                            "default": 3,
                        },
                    },
                },
            )
        ]

    # Create event store for resumability
    event_store = InMemoryEventStore()

    # Create session manager with event store and retry interval
    session_manager = StreamableHTTPSessionManager(
        app=app,
        event_store=event_store,
        retry_interval=retry_interval,
    )

    async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(starlette_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            logger.info(f"SSE Polling Demo server started on port {port}")
            logger.info("Try: POST /mcp with tools/call for 'process_batch'")
            yield
            logger.info("Server shutting down...")

    starlette_app = Starlette(
        debug=True,
        routes=[
            Mount("/mcp", app=handle_streamable_http),
        ],
        lifespan=lifespan,
    )

    import uvicorn

    uvicorn.run(starlette_app, host="127.0.0.1", port=port)
    return 0


if __name__ == "__main__":
    main()
