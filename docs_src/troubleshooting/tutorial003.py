from mcp.server import MCPServer

mcp = MCPServer("Weather")


@mcp.tool()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."


app = mcp.streamable_http_app()
