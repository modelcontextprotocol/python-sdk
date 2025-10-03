"""
Async tool with progress notifications example.

cd to the `examples/snippets/clients` directory and run:
    uv run server async_tool_progress stdio
"""

import anyio

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Async Tool Progress")


@mcp.tool(invocation_modes=["async"])
async def batch_process(items: list[str], ctx: Context[ServerSession, None]) -> list[str]:
    """Process a batch of items with detailed progress reporting."""
    await ctx.info(f"Starting batch processing of {len(items)} items")

    results: list[str] = []

    for i, item in enumerate(items):
        await ctx.debug(f"Processing item {i + 1}: {item}")

        # Simulate variable processing time
        processing_time = 0.3 + (len(item) * 0.1)
        await anyio.sleep(processing_time)

        # Report progress for this item
        progress = (i + 1) / len(items)
        await ctx.report_progress(progress, 1.0, f"Processed {i + 1}/{len(items)}: {item}")

        # Process the item
        result = f"PROCESSED_{item.upper()}"
        results.append(result)

        await ctx.debug(f"Item {i + 1} result: {result}")

    await ctx.info(f"Batch processing complete! Processed {len(results)} items")
    return results


@mcp.tool(invocation_modes=["async"])
async def data_pipeline(dataset: str, operations: list[str], ctx: Context[ServerSession, None]) -> dict[str, str]:
    """Execute a data processing pipeline with progress updates."""
    await ctx.info(f"Starting data pipeline for {dataset}")

    results: dict[str, str] = {}
    total_ops = len(operations)

    for i, operation in enumerate(operations):
        await ctx.debug(f"Executing operation: {operation}")

        # Simulate processing time that increases with complexity
        processing_time = 0.5 + (i * 0.2)
        await anyio.sleep(processing_time)

        # Report progress
        progress = (i + 1) / total_ops
        await ctx.report_progress(progress, 1.0, f"Completed {operation}")

        # Store result
        results[operation] = f"Result of {operation} on {dataset}"

    await ctx.info("Data pipeline complete!")
    return results


if __name__ == "__main__":
    mcp.run()
