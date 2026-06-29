"""SSE polling demo client.

Calls process_batch on the demo server, which periodically closes the SSE stream;
the client auto-reconnects via Last-Event-ID and resumes receiving messages.

Start the server (`uv run mcp-sse-polling-demo --port 3000`), then run
`uv run mcp-sse-polling-client --url http://localhost:3000/mcp`.
"""

import asyncio
import logging

import click
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def run_demo(url: str, items: int, checkpoint_every: int) -> None:
    print(f"\n{'=' * 60}")
    print("SSE Polling Demo Client")
    print(f"{'=' * 60}")
    print(f"Server URL: {url}")
    print(f"Processing {items} items with checkpoints every {checkpoint_every}")
    print(f"{'=' * 60}\n")

    async with streamable_http_client(url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            print("Initializing connection...")
            await session.initialize()
            print("Connected!\n")

            tools = await session.list_tools()
            print(f"Available tools: {[t.name for t in tools.tools]}\n")

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
