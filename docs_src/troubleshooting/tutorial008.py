from pydantic import BaseModel

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

mcp = MCPServer("Bistro")


class Confirmation(BaseModel):
    confirm: bool


@mcp.tool()
async def book_table(date: str, ctx: Context) -> str:
    """Book a table at the bistro."""
    result = await ctx.elicit(f"Book a table for {date}?", schema=Confirmation)
    if result.action == "accept" and result.data.confirm:
        return f"Booked for {date}."
    return "No booking made."


# Stateless HTTP: every request is its own world. No channel back to the client.
app = mcp.streamable_http_app(stateless_http=True)
