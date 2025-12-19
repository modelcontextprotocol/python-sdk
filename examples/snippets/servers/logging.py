"""
FastMCP Echo Server that sends log messages and prints to stderr
"""

import sys

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Logging and stdio test")


@mcp.tool()
async def log(ctx: Context[ServerSession, None]) -> str:
    await ctx.debug("Debug message")
    await ctx.info("Info message")
    print("Stderr message", file=sys.stderr)
    await ctx.warning("Warning message")
    await ctx.error("Error message")
    return "done"


if __name__ == "__main__":
    mcp.run(transport="stdio")
