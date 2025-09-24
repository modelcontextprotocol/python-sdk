"""
FastMCP async tools example showing different invocation modes.

cd to the `examples/snippets/clients` directory and run:
    uv run server async_tools stdio
"""

import asyncio

from mcp.server.fastmcp import Context, FastMCP

# Create an MCP server with async operations support
mcp = FastMCP("Async Tools Demo")


@mcp.tool()
def sync_tool(x: int) -> str:
    """An implicitly-synchronous tool."""
    return f"Sync result: {x * 2}"


@mcp.tool(invocation_modes=["async"])
async def async_only_tool(data: str, ctx: Context) -> str:  # type: ignore[type-arg]
    """An async-only tool that takes time to complete."""
    await ctx.info("Starting long-running analysis...")

    # Simulate long-running work with progress updates
    for i in range(5):
        await asyncio.sleep(0.5)
        progress = (i + 1) / 5
        await ctx.report_progress(progress, 1.0, f"Processing step {i + 1}/5")

    await ctx.info("Analysis complete!")
    return f"Async analysis result for: {data}"


@mcp.tool(invocation_modes=["sync", "async"])
def hybrid_tool(message: str, ctx: Context | None = None) -> str:  # type: ignore[type-arg]
    """A hybrid tool that works both sync and async."""
    if ctx:
        # Async mode - we have context for progress reporting
        import asyncio

        async def async_work():
            await ctx.info(f"Processing '{message}' asynchronously...")
            await asyncio.sleep(0.5)  # Simulate some work
            await ctx.debug("Async processing complete")

        # Run the async work (this is a bit of a hack for demo purposes)
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(async_work())
        except RuntimeError:
            pass  # No event loop running

    # Both sync and async modes return the same result
    return f"Hybrid result: {message.upper()}"


@mcp.tool(invocation_modes=["async"])
async def data_processing_tool(dataset: str, operations: list[str], ctx: Context) -> dict[str, str]:  # type: ignore[type-arg]
    """Simulate a complex data processing pipeline."""
    await ctx.info(f"Starting data processing pipeline for {dataset}")

    results: dict[str, str] = {}
    total_ops = len(operations)

    for i, operation in enumerate(operations):
        await ctx.debug(f"Executing operation: {operation}")

        # Simulate processing time
        processing_time = 0.5 + (i * 0.2)  # Increasing complexity
        await asyncio.sleep(processing_time)

        # Report progress
        progress = (i + 1) / total_ops
        await ctx.report_progress(progress, 1.0, f"Completed {operation}")

        # Store result
        results[operation] = f"Result of {operation} on {dataset}"

    await ctx.info("Data processing pipeline complete!")
    return results


@mcp.tool(invocation_modes=["async"])
async def file_analysis_tool(file_path: str, ctx: Context) -> str:  # type: ignore[type-arg]
    """Simulate file analysis with user interaction."""
    await ctx.info(f"Analyzing file: {file_path}")

    # Simulate initial analysis
    await asyncio.sleep(1)
    await ctx.report_progress(0.3, 1.0, "Initial scan complete")

    # Simulate finding an issue that requires user input
    await ctx.warning("Found potential security issue - requires user confirmation")

    # In a real implementation, you would use ctx.elicit() here to ask the user
    # For this demo, we'll just simulate the decision
    await asyncio.sleep(0.5)
    await ctx.info("User confirmed - continuing analysis")

    # Complete the analysis
    await asyncio.sleep(1)
    await ctx.report_progress(1.0, 1.0, "Analysis complete")

    return f"File analysis complete for {file_path}. No issues found after user review."


@mcp.tool(invocation_modes=["async"])
async def batch_operation_tool(items: list[str], ctx: Context) -> list[str]:  # type: ignore[type-arg]
    """Process a batch of items with detailed progress reporting."""
    await ctx.info(f"Starting batch operation on {len(items)} items")

    results: list[str] = []

    for i, item in enumerate(items):
        await ctx.debug(f"Processing item {i + 1}: {item}")

        # Simulate variable processing time
        processing_time = 0.2 + (len(item) * 0.1)
        await asyncio.sleep(processing_time)

        # Report progress for this item
        progress = (i + 1) / len(items)
        await ctx.report_progress(progress, 1.0, f"Processed {i + 1}/{len(items)}: {item}")

        # Process the item
        result = f"PROCESSED_{item.upper()}"
        results.append(result)

        await ctx.debug(f"Item {i + 1} result: {result}")

    await ctx.info(f"Batch operation complete! Processed {len(results)} items")
    return results


@mcp.tool(invocation_modes=["async"], keep_alive=1800)
async def long_running_task(task_name: str, ctx: Context) -> str:  # type: ignore[type-arg]
    """A long-running task with custom keep_alive duration."""
    await ctx.info(f"Starting long-running task: {task_name}")

    # Simulate extended processing
    await asyncio.sleep(2)
    await ctx.report_progress(0.5, 1.0, "Halfway through processing")
    await asyncio.sleep(2)

    await ctx.info(f"Task '{task_name}' completed successfully")
    return f"Long-running task '{task_name}' finished with 30-minute keep_alive"


@mcp.tool(invocation_modes=["async"], keep_alive=2)
async def quick_expiry_task(message: str, ctx: Context) -> str:  # type: ignore[type-arg]
    """A task with very short keep_alive for testing expiry."""
    await ctx.info(f"Quick task starting: {message}")
    await asyncio.sleep(1)
    return f"Quick task completed: {message} (expires in 2 seconds)"


if __name__ == "__main__":
    mcp.run()
