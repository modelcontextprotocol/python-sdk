from mcp.client.experimental.server_card import discover_server_cards


async def main() -> None:
    # Fetches the host's AI Catalog from `/.well-known/ai-catalog.json`, then
    # validates the Server Card of every MCP entry it references.
    for card in await discover_server_cards("https://dice.example.com"):
        print(card.name, card.version, "-", card.description)
        for remote in card.remotes or []:
            print("  ", remote.type, remote.url, remote.supported_protocol_versions)
