import httpx

from mcp.client.experimental.ai_catalog import fetch_ai_catalog, well_known_ai_catalog_url
from mcp.client.experimental.server_card import fetch_server_card
from mcp.shared.experimental.ai_catalog import MCP_SERVER_CARD_MEDIA_TYPE


async def main() -> None:
    # The lower-level building blocks, when you want to inspect the catalog
    # before fetching cards. Pass your own `http_client` to enforce a network
    # policy (timeouts, redirect caps, blocking private address ranges) when
    # discovering hosts you do not fully trust.
    async with httpx.AsyncClient() as http_client:
        catalog_url = well_known_ai_catalog_url("https://dice.example.com")
        catalog = await fetch_ai_catalog(catalog_url, http_client=http_client)

        for entry in catalog.entries:
            if entry.media_type != MCP_SERVER_CARD_MEDIA_TYPE or entry.url is None:
                continue
            card = await fetch_server_card(entry.url, http_client=http_client)
            print(entry.identifier, "->", card.name)
