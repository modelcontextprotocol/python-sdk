from pydantic import BaseModel, Field

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Enum Elicitation Example")


class ColorPreference(BaseModel):
    color: str = Field(
        description="Pick your favorite color",
        json_schema_extra={"enum": ["red", "green", "blue", "yellow"]},
    )


@mcp.tool()
async def pick_color(ctx: Context[ServerSession, None]) -> str:
    """Ask the user to pick a color from a list."""
    result = await ctx.elicit(
        message="Choose a color:",
        schema=ColorPreference,
    )
    if result.action == "accept":
        return f"You picked: {result.data.color}"
    return "No color selected"
