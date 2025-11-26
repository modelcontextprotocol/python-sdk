"""
SSE Polling Example Client

Demonstrates client-side behavior during server-initiated SSE disconnect.

Key features:
- Automatic reconnection when server closes SSE stream
- Event replay via Last-Event-ID header (handled internally by the transport)
- Progress notifications via logging callback

This client connects to the SSE polling server and calls the `long-task` tool.
The server disconnects at 50% progress, and the client automatically reconnects
to receive remaining progress updates.

Run:
    # First start the server:
    uv run examples/snippets/servers/sse_polling_server.py

    # Then run this client:
    uv run examples/snippets/clients/sse_polling_client.py
"""

import asyncio
import logging

from mcp import ClientSession
from mcp.client.streamable_http import StreamableHTTPReconnectionOptions, streamablehttp_client
from mcp.types import LoggingMessageNotificationParams, TextContent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    print("SSE Polling Example Client")
    print("=" * 50)
    print()

    # Track notifications received via the logging callback
    notifications_received: list[str] = []

    async def logging_callback(params: LoggingMessageNotificationParams) -> None:
        """Called when a log message notification is received from the server."""
        data = params.data
        if data:
            data_str = str(data)
            notifications_received.append(data_str)
            print(f"[Progress] {data_str}")

    # Configure reconnection behavior
    reconnection_options = StreamableHTTPReconnectionOptions(
        initial_reconnection_delay=1.0,  # Start with 1 second
        max_reconnection_delay=30.0,  # Cap at 30 seconds
        reconnection_delay_grow_factor=1.5,  # Exponential backoff
        max_retries=5,  # Try up to 5 times
    )

    print("[Client] Connecting to server...")

    async with streamablehttp_client(
        "http://localhost:3001/mcp",
        reconnection_options=reconnection_options,
    ) as (read_stream, write_stream, get_session_id):
        # Create session with logging callback to receive progress notifications
        async with ClientSession(
            read_stream,
            write_stream,
            logging_callback=logging_callback,
        ) as session:
            # Initialize the session
            await session.initialize()
            session_id = get_session_id()
            print(f"[Client] Connected! Session ID: {session_id}")

            # List available tools
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"[Client] Available tools: {tool_names}")
            print()

            # Call the long-running task
            print("[Client] Calling long-task tool...")
            print("[Client] The server will disconnect at 50% and we'll auto-reconnect")
            print()

            # Call the tool
            result = await session.call_tool("long-task", {})

            print()
            print("[Client] Task completed!")
            if result.content and isinstance(result.content[0], TextContent):
                print(f"[Result] {result.content[0].text}")
            else:
                print("[Result] No content")
            print()
            print(f"[Summary] Received {len(notifications_received)} progress notifications")


if __name__ == "__main__":
    asyncio.run(main())
