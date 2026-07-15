from mcp.server.experimental.ai_catalog import mount_ai_catalog, server_card_entry
from mcp.server.experimental.server_card import build_server_card, mount_server_card
from mcp.server.lowlevel import Server
from mcp.shared.experimental.ai_catalog import AICatalog
from mcp.shared.experimental.server_card import Remote, Repository

# The card's identity is read from the server: version and description are
# required (a card without them cannot be built), title/website/icons are copied
# if set.
server = Server(
    "dice-roller",
    version="1.0.0",
    title="Dice Roller",
    description="Rolls dice for tabletop games.",
    website_url="https://dice.example.com",
)

# `name` is the reverse-DNS `namespace/name` identifier, passed explicitly
# because the server's display name is free-form. `remotes` advertises where the
# server can actually be reached.
card = build_server_card(
    server,
    name="com.example/dice-roller",
    remotes=[Remote(type="streamable-http", url="https://dice.example.com/mcp")],
    repository=Repository(url="https://github.com/example/dice", source="github"),
)

# Serve the card next to the MCP endpoint, and advertise it in the host's AI
# Catalog at `/.well-known/ai-catalog.json`. The catalog entry points at the
# absolute URL the card is served from.
app = server.streamable_http_app()
mount_server_card(app, card, path="/mcp/server-card")

card_url = "https://dice.example.com/mcp/server-card"
catalog = AICatalog(entries=[server_card_entry(card, card_url)])
mount_ai_catalog(app, catalog)
