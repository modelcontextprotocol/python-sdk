from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server import MCPServer

mcp = MCPServer("Weather")


@mcp.tool()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."


# The mount works. The MCP app's own lifespan never runs.
app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())])
