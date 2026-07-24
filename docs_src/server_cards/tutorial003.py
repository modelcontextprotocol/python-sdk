import httpx2

from mcp.client.experimental.server_card import create_server_card_request, parse_server_card_response
from mcp.shared.experimental.server_card import ServerCard


class CardStore:
    """Your host's cache. Anything that keeps a card and its ETag per URL works."""

    def __init__(self) -> None:
        self.cards: dict[str, ServerCard] = {}
        self.etags: dict[str, str] = {}


async def refresh(store: CardStore, http: httpx2.AsyncClient, url: str) -> ServerCard:
    request = create_server_card_request(url, if_none_match=store.etags.get(url))
    response = await http.send(request)
    if response.status_code != 304:  # an unchanged card costs a 304
        store.cards[url] = parse_server_card_response(response)
        if "etag" in response.headers:
            store.etags[url] = response.headers["etag"]
    return store.cards[url]
