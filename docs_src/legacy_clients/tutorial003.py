from mcp.server import MCPServer
from mcp.server.mcpserver import Context

mcp = MCPServer("Bookshop")

STOCK = {"Dune": 3}


@mcp.resource("stock://{title}")
def stock(title: str) -> str:
    """How many copies of one book are on the shelf."""
    return f"{STOCK[title]} in stock"


@mcp.tool()
async def restock(title: str, copies: int, ctx: Context) -> str:
    """Put copies of a book back on the shelf."""
    STOCK[title] = STOCK.get(title, 0) + copies
    await ctx.notify_resource_updated(f"stock://{title}")
    await ctx.session.send_resource_updated(f"stock://{title}")
    return f"{STOCK[title]} in stock"
