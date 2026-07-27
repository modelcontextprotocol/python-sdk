from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

mcp = MCPServer("Notes")


@mcp.tool()
def add_note(text: str) -> str:
    """Save a note."""
    return f"Saved: {text}"


security = TransportSecuritySettings(
    allowed_hosts=["mcp.example.com", "mcp.example.com:*"],
    allowed_origins=["https://app.example.com"],
)
app = mcp.streamable_http_app(transport_security=security)
