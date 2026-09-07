from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

mcp = MCPServer("Weather")


@mcp.tool()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."


app = mcp.streamable_http_app(
    transport_security=TransportSecuritySettings(
        allowed_hosts=["mcp.example.com", "mcp.example.com:*"],
        allowed_origins=["http://mcp.example.com", "http://mcp.example.com:*"],
    )
)
