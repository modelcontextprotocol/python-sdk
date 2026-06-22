"""Ingest MCP Server Cards (SEP-2127).

WARNING: These APIs are experimental and may change without notice.

A client discovers how to connect to the servers a host advertises by
fetching its AI Catalog and the Server Cards the catalog references::

    from mcp.client.experimental.server_card import discover_server_cards

    for card in await discover_server_cards("https://dice.example.com"):
        for remote in card.remotes or []:
            print(remote.type, remote.url, remote.supported_protocol_versions)

Returned :class:`ServerCard` objects are validated; malformed documents raise
``pydantic.ValidationError``. A missing ``$schema`` key is tolerated — see
``ServerCard.schema_uri``.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from mcp.client.experimental.ai_catalog import fetch_ai_catalog, well_known_ai_catalog_url
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.experimental.ai_catalog.types import (
    MCP_CATALOG_WELL_KNOWN_PATH,
    MCP_SERVER_CARD_MEDIA_TYPE,
)
from mcp.shared.experimental.server_card.types import ServerCard

__all__ = ["fetch_server_card", "load_server_card", "discover_server_cards"]


async def fetch_server_card(url: str, *, http_client: httpx.AsyncClient | None = None) -> ServerCard:
    """Fetch and validate the Server Card at ``url``.

    ``url`` is the card's location, typically taken from an AI Catalog
    entry's ``url``. Pass an existing ``http_client`` to reuse connection
    pooling / auth, otherwise a short-lived client with MCP defaults is used.

    Raises:
        httpx.HTTPError: If the request fails or returns a non-2xx status.
        pydantic.ValidationError: If the document is not a valid Server Card.
    """
    if http_client is None:
        async with create_mcp_http_client() as client:
            return await fetch_server_card(url, http_client=client)
    response = await http_client.get(url, headers={"Accept": f"{MCP_SERVER_CARD_MEDIA_TYPE}, application/json"})
    response.raise_for_status()
    return ServerCard.model_validate(response.json())


async def discover_server_cards(url: str, *, http_client: httpx.AsyncClient | None = None) -> list[ServerCard]:
    """Discover the MCP servers advertised by the host of ``url``.

    Fetches the host's AI Catalog from ``/.well-known/ai-catalog.json``
    (falling back to the MCP-scoped ``/.well-known/mcp/catalog.json`` on a
    404), then validates the Server Card of every MCP server entry — fetched
    from the entry's ``url`` or read from its inline ``data``. Entries with
    other media types are ignored.

    Card URLs are taken from the fetched catalog and may point anywhere,
    including other domains. Non-http(s) card URLs are rejected; beyond that,
    applications discovering hosts they don't trust should pass an
    ``http_client`` that enforces their network policy (e.g. rejecting
    private address ranges or capping redirects) — the SDK imposes none
    because loopback and intranet servers are legitimate discovery targets.

    Raises:
        ValueError: If ``url`` is not an absolute http(s) URL, or the catalog
            references a card at a non-http(s) URL.
        httpx.HTTPError: If a request fails or returns a non-2xx status.
        pydantic.ValidationError: If the catalog or a referenced card is invalid.
    """
    if http_client is None:
        async with create_mcp_http_client() as client:
            return await discover_server_cards(url, http_client=client)

    catalog_url = well_known_ai_catalog_url(url)
    try:
        catalog = await fetch_ai_catalog(catalog_url, http_client=http_client)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        catalog_url = well_known_ai_catalog_url(url, well_known_path=MCP_CATALOG_WELL_KNOWN_PATH)
        catalog = await fetch_ai_catalog(catalog_url, http_client=http_client)

    cards: list[ServerCard] = []
    for entry in catalog.entries:
        if entry.media_type != MCP_SERVER_CARD_MEDIA_TYPE:
            continue
        if entry.url is not None:
            # Entry URLs are usually absolute; resolve relative ones against
            # the catalog's location. The catalog is remote input — never
            # follow it to a non-http(s) scheme.
            card_url = urljoin(catalog_url, entry.url)
            if urlsplit(card_url).scheme not in ("http", "https"):
                raise ValueError(f"catalog entry {entry.identifier!r} has a non-http(s) card URL: {card_url!r}")
            cards.append(await fetch_server_card(card_url, http_client=http_client))
        else:
            cards.append(ServerCard.model_validate(entry.data))
    return cards


def load_server_card(path: str | Path) -> ServerCard:
    """Load and validate a Server Card from a JSON file.

    Raises:
        OSError: If the file cannot be read.
        json.JSONDecodeError: If the file is not valid JSON.
        pydantic.ValidationError: If the document is not a valid Server Card.
    """
    text = Path(path).read_text(encoding="utf-8")
    return ServerCard.model_validate(json.loads(text))
