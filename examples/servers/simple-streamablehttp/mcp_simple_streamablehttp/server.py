import logging

import anyio
import click
import mcp_types as types
import uvicorn
from mcp.server import Server, ServerRequestContext
from starlette.middleware.cors import CORSMiddleware

from .event_store import InMemoryEventStore

logger = logging.getLogger(__name__)


async def handle_list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="start-notification-stream",
                description="Sends a stream of notifications with configurable count and interval",
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
                            "description": "Identifier of the caller to include in notifications",
                        },
                    },
                },
            )
        ]
    )


async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    arguments = params.arguments or {}
    interval = arguments.get("interval", 1.0)
    count = arguments.get("count", 5)
    caller = arguments.get("caller", "unknown")

    for i in range(count):
        notification_msg = f"[{i + 1}/{count}] Event from '{caller}' - Use Last-Event-ID to resume if disconnected"
        await ctx.session.send_log_message(  # pyright: ignore[reportDeprecated]
            level="info",
            data=notification_msg,
            logger="notification_stream",
            # Routes the notification to this request's response stream; without it,
            # notifications go to the standalone SSE stream (or nowhere if GET is unsupported).
            related_request_id=ctx.request_id,
        )
        logger.debug(f"Sent notification {i + 1}/{count} for caller: {caller}")
        if i < count - 1:
            await anyio.sleep(interval)

    # No related_request_id, so this goes out over the standalone SSE stream (GET request)
    await ctx.session.send_resource_updated(uri="http:///test_resource")
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=(f"Sent {count} notifications with {interval}s interval for caller: {caller}"),
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
) -> int:
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    app = Server(
        "mcp-streamable-http-demo",
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )

    # Event store enables resumability: clients replay missed SSE events by sending
    # Last-Event-ID on reconnect. In-memory is for demos; use persistent storage in production.
    event_store = InMemoryEventStore()

    starlette_app = app.streamable_http_app(
        event_store=event_store,
        json_response=json_response,
        debug=True,
    )

    # CORS so browser clients can read Mcp-Session-Id; wrapping the ASGI app keeps headers on error responses
    starlette_app = CORSMiddleware(
        starlette_app,
        allow_origins=["*"],  # streamable_http_app() enforces localhost-only Origin by default
        allow_methods=["GET", "POST", "DELETE"],
        expose_headers=["Mcp-Session-Id"],
    )

    uvicorn.run(starlette_app, host="127.0.0.1", port=port)

    return 0
