"""
FastMCP Example showing parameter descriptions
"""

from pydantic import Field

from mcp.server.fastmcp import FastMCP

# Create server
mcp = FastMCP("Parameter Descriptions Server")


@mcp.tool()
def greet_user(
    name: str = Field(description="The name of the person to greet"),
    title: str = Field(description="Optional title like Mr/Ms/Dr", default=""),
    times: int = Field(description="Number of times to repeat the greeting", default=1),
) -> str:
    """Greet a user with optional title and repetition"""
    greeting = f"Hello {title + ' ' if title else ''}{name}!"
    return "\n".join([greeting] * times)
