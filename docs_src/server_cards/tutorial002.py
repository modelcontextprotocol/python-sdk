import httpx2

from mcp import Client
from mcp.client.experimental.server_card import discover_server_cards, reconcile_server_card
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.experimental.server_card import resolve_remote


async def main() -> None:
    result = await discover_server_cards("https://example.com/docs")
    for listing in result.listings:
        print(listing.entry.identifier, "listed on", listing.listing_domain, "hosted at", listing.hosting_domain)

    chosen = result.listings[0]  # your host app: consent UI, dedup on chosen.card.endpoint_urls()
    assert chosen.card.remotes is not None
    resolved = resolve_remote(chosen.card.remotes[0], {"token": "..."})  # ValueError names missing inputs

    async with httpx2.AsyncClient(headers=resolved.headers, follow_redirects=True) as http_client:
        transport = streamable_http_client(resolved.url, http_client=http_client)
        async with Client(transport) as client:
            for mismatch in reconcile_server_card(chosen.card, client.server_info):  # advisory: runtime wins
                print("card mismatch:", mismatch.field, mismatch.card_value, mismatch.runtime_value)
