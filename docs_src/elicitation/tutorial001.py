from pydantic import BaseModel, Field

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

mcp = MCPServer("Bistro")


class AlternativeDate(BaseModel):
    accept_alternative: bool = Field(description="Try another date?")
    date: str = Field(default="2025-12-26", description="Alternative date (YYYY-MM-DD)")


@mcp.tool()
async def book_table(date: str, party_size: int, ctx: Context) -> str:
    """Book a table at the bistro."""
    if date != "2025-12-25":
        return f"Booked a table for {party_size} on {date}."

    result = await ctx.elicit(
        message=f"No tables for {party_size} on {date}. Would you like to try another date?",
        schema=AlternativeDate,
    )
    if result.action == "accept" and result.data.accept_alternative:
        return await book_table(result.data.date, party_size, ctx)
    return "No booking made."
