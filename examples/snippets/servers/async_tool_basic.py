"""
Basic async tool example.

cd to the `examples/snippets/clients` directory and run:
    uv run server async_tool_basic stdio
"""

import anyio

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Async Tool Basic")


@mcp.tool(invocation_modes=["async"])
async def analyze_data(dataset: str, ctx: Context[ServerSession, None]) -> str:
    """Analyze a dataset asynchronously with progress updates."""
    await ctx.info(f"Starting analysis of {dataset}")

    # Simulate analysis with progress updates
    for i in range(5):
        await anyio.sleep(0.5)
        progress = (i + 1) / 5
        await ctx.report_progress(progress, 1.0, f"Processing step {i + 1}/5")

    await ctx.info("Analysis complete")
    return f"Analysis results for {dataset}: 95% accuracy achieved"


@mcp.tool(invocation_modes=["sync", "async"])
async def process_text(text: str, ctx: Context[ServerSession, None]) -> str:
    """Process text in sync or async mode."""

    await ctx.info(f"Processing text asynchronously: {text[:20]}...")
    await anyio.sleep(0.3)

    return f"Processed: {text.upper()}"


if __name__ == "__main__":
    mcp.run()
