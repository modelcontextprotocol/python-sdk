from mcp.server import MCPServer
from mcp.server.experimental.server_card import mount_discovery
from mcp.shared.experimental.server_card import Remote, ServerCard

mcp = MCPServer(
    name="weather",
    version="1.4.0",
    description="Hourly forecasts.",
    website_url="https://example.com",
)

card = ServerCard.from_server(
    mcp,
    name="com.example/weather",
    remotes=[Remote(type="streamable-http", url="https://mcp.example.com/mcp")],
)

app = mcp.streamable_http_app()
mount_discovery(app, card, public_url="https://mcp.example.com")
