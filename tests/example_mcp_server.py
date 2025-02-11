#
# Small Demo server using FastMCP and illustrating debugging and notification streams
#

import logging
from mcp.server.fastmcp import FastMCP, Context
import time

mcp = FastMCP("MCP EXAMPLE SERVER", debug=True, log_level="DEBUG")

logger = logging.getLogger(__name__)

logger.debug(f"MCP STARTING EXAMPLE SERVER")

@mcp.resource("config://app")
def get_config() -> str:
    """Static configuration data"""
    return "Test Server 2024-02-25"

@mcp.tool()
async def simple_tool(x:float, y:float, ctx:Context) -> str:
    logger.debug("IN SIMPLE_TOOL")
    await ctx.report_progress(1, 2)
    return x*y

@mcp.tool()
async def simple_tool_with_logging(x:float, y:float, ctx:Context) -> str:
    await ctx.info(f"Processing Simple Tool")
    logger.debug("IN SIMPLE_TOOL")
    await ctx.report_progress(1, 2)
    return x*y

