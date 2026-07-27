from mcp.server import MCPServer
from mcp.server.mcpserver import Context

mcp = MCPServer("Bookshop")


@mcp.tool()
async def import_catalog(urls: list[str], ctx: Context) -> str:
    """Import book records from a list of catalog URLs."""
    for done, url in enumerate(urls, start=1):
        await ctx.report_progress(done, total=len(urls), message=f"Imported {url}")
    return f"Imported {len(urls)} records."
