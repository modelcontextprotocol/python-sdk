from mcp.server import MCPServer
from mcp.server.mcpserver import Context

mcp = MCPServer("Bookshop")


@mcp.resource("catalog://genres")
def genres() -> str:
    """The genres the catalog is organised into."""
    return "fiction, non-fiction, poetry"


@mcp.tool()
async def describe_catalog(ctx: Context) -> str:
    """Describe how the catalog is organised."""
    [contents] = await ctx.read_resource("catalog://genres")
    return f"The catalog is organised into: {contents.content}"
