from mcp.server import MCPServer
from mcp.server.mcpserver import Context

mcp = MCPServer("Bookshop")


def recommend_book(genre: str) -> str:
    """Recommend a book in the given genre."""
    return f"In {genre}, try 'Dune'."


@mcp.tool()
async def enable_recommendations(ctx: Context) -> str:
    """Switch on the recommendation tool."""
    mcp.add_tool(recommend_book)
    await ctx.session.send_tool_list_changed()
    return "Recommendations are now available."
