import contextlib
import logging

import anyio
import click
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamableHttp import (
    StreamableHTTPServerTransport,
)
from starlette.applications import Starlette
from starlette.routing import Mount

logger = logging.getLogger(__name__)
# Global task group that will be initialized in the lifespan
task_group = None


@contextlib.asynccontextmanager
async def lifespan(app):
    """Application lifespan context manager for managing task group."""
    global task_group

    async with anyio.create_task_group() as tg:
        task_group = tg
        logger.info("Application started, task group initialized!")
        try:
            yield
        finally:
            logger.info("Application shutting down, cleaning up resources...")
            if task_group:
                tg.cancel_scope.cancel()
                task_group = None
            logger.info("Resources cleaned up successfully.")


@click.command()
@click.option("--port", default=3000, help="Port to listen on for HTTP")
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
    log_level: str,
    json_response: bool,
) -> int:
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    app = Server("mcp-streamable-http-stateless-demo")

    @app.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        ctx = app.request_context
        interval = arguments.get("interval", 1.0)
        count = arguments.get("count", 5)
        caller = arguments.get("caller", "unknown")

        # Send the specified number of notifications with the given interval
        for i in range(count):
            await ctx.session.send_log_message(
                level="info",
                data=f"Notification {i+1}/{count} from caller: {caller}",
                logger="notification_stream",
                related_request_id=ctx.request_id,
            )
            if i < count - 1:  # Don't wait after the last notification
                await anyio.sleep(interval)

        return [
            types.TextContent(
                type="text",
                text=(
                    f"Sent {count} notifications with {interval}s interval"
                    f" for caller: {caller}"
                ),
            )
        ]

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="start-notification-stream",
                description=(
                    "Sends a stream of notifications with configurable count"
                    " and interval"
                ),
                inputSchema={
                    "type": "object",
                    "required": ["interval", "count", "caller"],
                    "properties": {
                        "interval": {
                            "type": "number",
                            "description": "Interval between notifications in seconds",
                        },
                        "count": {
                            "type": "number",
                            "description": "Number of notifications to send",
                        },
                        "caller": {
                            "type": "string",
                            "description": (
                                "Identifier of the caller to include in notifications"
                            ),
                        },
                    },
                },
            )
        ]

    # ASGI handler for stateless HTTP connections
    async def handle_streamable_http(scope, receive, send):
        logger.debug("Creating new transport")
        # Use lock to prevent race conditions when creating new sessions
        http_transport = StreamableHTTPServerTransport(
            mcp_session_id=None,
            is_json_response_enabled=json_response,
        )
        async with http_transport.connect() as streams:
            read_stream, write_stream = streams

            if not task_group:
                raise RuntimeError("Task group is not initialized")

            async def run_server():
                await app.run(
                    read_stream,
                    write_stream,
                    app.create_initialization_options(),
                    # Runs in standalone mode for stateless deployments
                    # where clients perform initialization with any node
                    standalone_mode=True,
                )

            # Start server task
            task_group.start_soon(run_server)

            # Handle the HTTP request and return the response
            await http_transport.handle_request(scope, receive, send)

    # Create an ASGI application using the transport
    starlette_app = Starlette(
        debug=True,
        routes=[
            Mount("/mcp", app=handle_streamable_http),
        ],
        lifespan=lifespan,
    )

    import uvicorn

    uvicorn.run(starlette_app, host="0.0.0.0", port=port)

    return 0
