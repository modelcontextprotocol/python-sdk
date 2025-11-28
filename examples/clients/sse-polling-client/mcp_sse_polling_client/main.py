"""
SSE Polling Demo Client

Demonstrates the client-side auto-reconnect for SSE polling pattern.

This client connects to the SSE Polling Demo server and calls process_batch,
which triggers periodic server-side stream closes. The client automatically
reconnects using Last-Event-ID and resumes receiving messages.

Run with:
    # First start the server:
    uv run mcp-sse-polling-demo --port 3000

    # Then run this client:
    uv run mcp-sse-polling-client --url http://localhost:3000/mcp
"""

import asyncio
import logging

import click
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)


async def run_demo(url: str, items: int, checkpoint_every: int) -> None:
    """Run the SSE polling demo."""
    print(f"\n{'=' * 60}")
    print("SSE Polling Demo Client")
    print(f"{'=' * 60}")
    print(f"Server URL: {url}")
    print(f"Processing {items} items with checkpoints every {checkpoint_every}")
    print(f"{'=' * 60}\n")

    async with streamablehttp_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize the connection
            print("Initializing connection...")
            await session.initialize()
            print("Connected!\n")

            # List available tools
            tools = await session.list_tools()
            print(f"Available tools: {[t.name for t in tools.tools]}\n")

            # Call the process_batch tool
            print(f"Calling process_batch(items={items}, checkpoint_every={checkpoint_every})...\n")
            print("-" * 40)

            result = await session.call_tool(
                "process_batch",
                {
                    "items": items,
                    "checkpoint_every": checkpoint_every,
                },
            )

            print("-" * 40)
            if result.content:
                content = result.content[0]
                text = getattr(content, "text", str(content))
                print(f"\nResult: {text}")
            else:
                print("\nResult: No content")
            print(f"{'=' * 60}\n")


@click.command()
@click.option(
    "--url",
    default="http://localhost:3000/mcp",
    help="Server URL",
)
@click.option(
    "--items",
    default=10,
    help="Number of items to process",
)
@click.option(
    "--checkpoint-every",
    default=3,
    help="Checkpoint interval",
)
@click.option(
    "--log-level",
    default="INFO",
    help="Logging level",
)
def main(url: str, items: int, checkpoint_every: int, log_level: str) -> None:
    """Run the SSE Polling Demo client."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    # Suppress noisy HTTP client logging
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    asyncio.run(run_demo(url, items, checkpoint_every))


if __name__ == "__main__":
    main()
