"""
Async tool with immediate result example.

cd to the `examples/snippets/clients` directory and run:
    uv run server async_tool_immediate stdio
"""

import asyncio

from mcp import types
from mcp.server.fastmcp import Context, FastMCP

mcp = FastMCP("Async Tool Immediate")


async def provide_immediate_feedback(operation: str) -> list[types.ContentBlock]:
    """Provide immediate feedback while async operation starts."""
    return [types.TextContent(type="text", text=f"Starting {operation} operation. This will take a moment.")]


@mcp.tool(invocation_modes=["async"], immediate_result=provide_immediate_feedback)
async def long_analysis(operation: str, ctx: Context) -> str:  # type: ignore[type-arg]
    """Perform long-running analysis with immediate user feedback."""
    await ctx.info(f"Beginning {operation} analysis")

    # Simulate long-running work
    for i in range(4):
        await asyncio.sleep(1)
        progress = (i + 1) / 4
        await ctx.report_progress(progress, 1.0, f"Analysis step {i + 1}/4")

    return f"Analysis '{operation}' completed with detailed results"


if __name__ == "__main__":
    mcp.run()
