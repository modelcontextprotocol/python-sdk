"""MCPServer Echo Server that sends log messages and progress updates to the client"""

import asyncio

from mcp.server.mcpserver import Context, MCPServer

# Create server
mcp = MCPServer("Echo Server with logging and progress updates")


@mcp.tool()
async def echo(text: str, ctx: Context) -> str:
    """Echo the input text sending log messages and progress updates during processing."""
    await ctx.report_progress(progress=0, total=100)
    
    # Test logging with objects (not just strings) - now valid per MCP spec
    await ctx.info({"status": "starting", "input_length": len(text), "text": text})

    await asyncio.sleep(2)

    await ctx.info("Halfway through processing echo for input: " + text)
    await ctx.report_progress(progress=50, total=100)

    await asyncio.sleep(2)

    # Test logging with a list
    await ctx.info(["processing", "complete", "returning"])
    await ctx.report_progress(progress=100, total=100)

    # Progress notifications are process asynchronously by the client.
    # A small delay here helps ensure the last notification is processed by the client.
    await asyncio.sleep(0.1)

    return text
