from collections.abc import AsyncIterator

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

mcp = MCPServer("Bookshop")


async def fetch_records(feed_url: str) -> AsyncIterator[str]:
    for title in ("Dune", "Neuromancer", "Hyperion"):
        yield f"{feed_url}#{title}"


@mcp.tool()
async def import_feed(feed_url: str, ctx: Context) -> str:
    """Import every record a catalog feed yields."""
    imported = 0
    async for record in fetch_records(feed_url):
        imported += 1
        await ctx.report_progress(imported, message=f"Imported {record}")
    return f"Imported {imported} records."
