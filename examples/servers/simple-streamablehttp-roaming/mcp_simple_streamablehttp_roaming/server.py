"""
MCP StreamableHTTP server with session roaming support.

This server demonstrates how to deploy MCP servers across multiple instances
with full session roaming support using a shared Redis EventStore.
"""

import contextlib
import logging
import socket
from collections.abc import AsyncIterator
from typing import Any

import click
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from .redis_event_store import RedisEventStore

# Configure logging
logger = logging.getLogger(__name__)


@click.command()
@click.option("--port", default=3001, help="Port to listen on")
@click.option("--instance-id", default=None, help="Instance identifier (default: hostname)")
@click.option(
    "--redis-url",
    default="redis://localhost:6379",
    help="Redis connection URL for EventStore",
)
@click.option(
    "--log-level",
    default="INFO",
    help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
)
@click.option(
    "--json-response",
    is_flag=True,
    default=False,
    help="Enable JSON responses instead of SSE streams",
)
def main(
    port: int,
    instance_id: str | None,
    redis_url: str,
    log_level: str,
    json_response: bool,
) -> int:
    """Start MCP server with session roaming support."""
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Default instance ID to hostname if not provided
    if instance_id is None:
        instance_id = socket.gethostname()

    logger.info(f"Starting MCP server instance: {instance_id}")
    logger.info(f"Port: {port}")
    logger.info(f"Redis EventStore: {redis_url}")

    # Create MCP server
    app = Server(f"mcp-roaming-demo-{instance_id}")

    @app.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        """Handle tool calls - demonstrates which instance is serving the request."""
        if name == "get-instance-info":
            message = arguments.get("message", "")
            response_text = f"Instance: {instance_id}\nPort: {port}\n"
            if message:
                response_text += f"Message: {message}\n"
            response_text += "\n✅ This demonstrates session roaming - you can call this from any instance!"

            return [
                types.TextContent(
                    type="text",
                    text=response_text,
                )
            ]
        else:
            raise ValueError(f"Unknown tool: {name}")

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        """List available tools."""
        return [
            types.Tool(
                name="get-instance-info",
                description="Returns information about which server instance is handling this request. "
                "Use this to verify session roaming across multiple instances.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Optional message to include in the response",
                        },
                    },
                },
            )
        ]

    # Create Redis EventStore for session roaming
    # This is THE KEY to session roaming:
    # - Stores events persistently in Redis
    # - Shared across all server instances
    # - Enables any instance to serve any session
    event_store = RedisEventStore(redis_url=redis_url)

    # Create session manager with EventStore
    # The EventStore parameter alone enables BOTH:
    # 1. Event replay (resumability)
    # 2. Session roaming (distributed sessions)
    session_manager = StreamableHTTPSessionManager(
        app=app,
        event_store=event_store,  # This enables session roaming! ✅
        json_response=json_response,
    )

    # ASGI handler for StreamableHTTP
    async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
        """Handle incoming StreamableHTTP requests."""
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        """Manage application lifecycle."""
        async with session_manager.run():
            logger.info("=" * 70)
            logger.info(f"🚀 Instance {instance_id} started with SESSION ROAMING!")
            logger.info("=" * 70)
            logger.info("✓ Redis EventStore enables session roaming across instances")
            logger.info("✓ Sessions can move between any server instance")
            logger.info("✓ No sticky sessions required!")
            logger.info("✓ Horizontal scaling supported")
            logger.info("=" * 70)
            try:
                yield
            finally:
                logger.info(f"Instance {instance_id} shutting down...")
                await event_store.disconnect()

    # Create Starlette ASGI application
    starlette_app = Starlette(
        debug=True,
        routes=[
            Mount("/mcp", app=handle_streamable_http),
        ],
        lifespan=lifespan,
    )

    # Add CORS middleware to expose MCP-Session-ID header
    starlette_app = CORSMiddleware(
        starlette_app,
        allow_origins=["*"],  # Adjust for production
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
        expose_headers=["MCP-Session-ID"],
    )

    # Start server
    import uvicorn

    uvicorn.run(starlette_app, host="0.0.0.0", port=port)

    return 0
