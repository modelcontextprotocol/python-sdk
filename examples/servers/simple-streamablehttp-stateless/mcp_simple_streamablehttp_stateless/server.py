import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

import anyio
import click
import uvicorn
from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

logger = logging.getLogger(__name__)


async def handle_call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
    interval = params.arguments.get("interval", 1.0) if params.arguments else 1.0
    count = params.arguments.get("count", 5) if params.arguments else 5
    caller = params.arguments.get("caller", "unknown") if params.arguments else "unknown"

    # Send the specified number of notifications with the given interval
    for i in range(count):
        await ctx.session.send_log_message(
            level="info",
            data=f"Notification {i + 1}/{count} from caller: {caller}",
            logger="notification_stream",
            related_request_id=ctx.request_id,
        )
        if i < count - 1:  # Don't wait after the last notification
            await anyio.sleep(interval)

    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=(f"Sent {count} notifications with {interval}s interval for caller: {caller}"),
            )
        ]
    )


async def handle_list_tools(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="start-notification-stream",
                description=("Sends a stream of notifications with configurable count and interval"),
                input_schema={
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
                            "description": ("Identifier of the caller to include in notifications"),
                        },
                    },
                },
            )
        ]
    )


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
) -> None:
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    app = Server(
        "mcp-streamable-http-stateless-demo",
        on_call_tool=handle_call_tool,
        on_list_tools=handle_list_tools,
    )

    # Create the session manager with true stateless mode
    session_manager = StreamableHTTPSessionManager(
        app=app,
        event_store=None,
        json_response=json_response,
        stateless=True,
    )

    async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        """Context manager for session manager."""
        async with session_manager.run():
            logger.info("Application started with StreamableHTTP session manager!")
            try:
                yield
            finally:
                logger.info("Application shutting down...")

    # Create an ASGI application using the transport
    starlette_app = Starlette(
        debug=True,
        routes=[Mount("/mcp", app=handle_streamable_http)],
        lifespan=lifespan,
    )

    # Wrap ASGI application with CORS middleware to expose Mcp-Session-Id header
    # for browser-based clients (ensures 500 errors get proper CORS headers)
    starlette_app = CORSMiddleware(
        starlette_app,
        allow_origins=["*"],  # Allow all origins - adjust as needed for production
        allow_methods=["GET", "POST", "DELETE"],  # MCP streamable HTTP methods
        expose_headers=["Mcp-Session-Id"],
    )

    uvicorn.run(starlette_app, host="127.0.0.1", port=port)
