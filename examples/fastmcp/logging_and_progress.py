"""
FastMCP Echo Server that sends log messages and progress updates to the client
"""

import asyncio

from mcp.server.fastmcp import Context, FastMCP

# Create server
mcp = FastMCP("Echo Server with logging and progress updates")


@mcp.tool()
async def echo(text: str, ctx: Context) -> str:
    """Echo the input text sending log messages and progress updates during processing."""
    await ctx.report_progress(progress=0, total=100)
    await ctx.info("Starting to process echo for input: " + text)

    await asyncio.sleep(2)

    await ctx.info("Halfway through processing echo for input: " + text)
    await ctx.report_progress(progress=50, total=100)

    await asyncio.sleep(2)

    await ctx.info("Finished processing echo for input: " + text)
    await ctx.report_progress(progress=100, total=100)

    # Progress notifications are process asynchronously by the client.
    # A small delay here helps ensure the last notification is processed by the client.
    await asyncio.sleep(0.1)

    return text
