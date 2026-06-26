from pydantic import BaseModel

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

mcp = MCPServer("Library")


class CardHolder(BaseModel):
    name: str


@mcp.tool()
async def issue_card(ctx: Context) -> str:
    """Issue a new library card."""
    answer = await ctx.elicit("What name should go on the card?", schema=CardHolder)
    if answer.action == "accept":
        return f"Card issued to {answer.data.name}."
    return "No card issued."
