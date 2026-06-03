"""Generate and serve AI Catalogs.

WARNING: These APIs are experimental and may change without notice.

A server author advertises their MCP server by serving an AI Catalog from the
well-known path, with an entry pointing at the server's Server Card::

    from mcp.server.experimental.ai_catalog import mount_ai_catalog, server_card_entry
    from mcp.server.experimental.server_card import build_server_card, mount_server_card
    from mcp.shared.experimental.ai_catalog import AICatalog

    card = build_server_card(server, name="io.modelcontextprotocol.examples/dice-roller")

    app = server.streamable_http_app()
    mount_server_card(app, card, path="/server-card.json")
    catalog = AICatalog(entries=[server_card_entry(card, "https://dice.example.com/server-card.json")])
    mount_ai_catalog(app, catalog)          # GET /.well-known/ai-catalog.json

To write a catalog to a file instead, serialize it with
``catalog.model_dump_json(by_alias=True, exclude_none=True)``.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from mcp.shared.experimental.ai_catalog.types import (
    AI_CATALOG_MEDIA_TYPE,
    AI_CATALOG_WELL_KNOWN_PATH,
    MCP_SERVER_CARD_MEDIA_TYPE,
    MCP_SERVER_URN_PREFIX,
    AICatalog,
    CatalogEntry,
)
from mcp.shared.experimental.server_card.types import ServerCard

__all__ = ["DISCOVERY_HEADERS", "server_card_entry", "ai_catalog_route", "mount_ai_catalog"]

#: Response headers for discovery endpoints (catalogs and the artifacts they
#: reference). Browser-based clients must be able to read them: the discovery
#: spec makes the CORS headers a MUST and the caching header a SHOULD.
DISCOVERY_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "public, max-age=3600",
}


def server_card_entry(card: ServerCard, url: str) -> CatalogEntry:
    """Build the catalog entry advertising ``card``, served at ``url``.

    The entry's identifier is derived from the card's ``name`` per the MCP
    discovery extension (``urn:mcp:server:<name>``); display name, description
    and version are taken from the card. ``url`` should be the absolute URL
    the card is retrievable from, since catalogs may be fetched cross-domain.
    """
    return CatalogEntry(
        identifier=f"{MCP_SERVER_URN_PREFIX}{card.name}",
        display_name=card.title or card.name,
        media_type=MCP_SERVER_CARD_MEDIA_TYPE,
        url=url,
        description=card.description,
        version=card.version,
    )


def ai_catalog_route(catalog: AICatalog, *, path: str = AI_CATALOG_WELL_KNOWN_PATH) -> Route:
    """Build a Starlette GET route that serves ``catalog`` at ``path``.

    Add it to a new app — ``Starlette(routes=[ai_catalog_route(catalog)])`` —
    or an existing one via :func:`mount_ai_catalog`. The payload is serialized
    once and served with the CORS and caching headers discovery requires.
    """
    body = catalog.model_dump_json(by_alias=True, exclude_none=True).encode()

    async def endpoint(_request: Request) -> Response:
        return Response(body, media_type=AI_CATALOG_MEDIA_TYPE, headers=DISCOVERY_HEADERS)

    return Route(path, endpoint=endpoint, methods=["GET"], name="ai_catalog")


def mount_ai_catalog(app: Starlette, catalog: AICatalog, *, path: str = AI_CATALOG_WELL_KNOWN_PATH) -> None:
    """Attach an AI Catalog route to an existing Starlette application.

    Discovery expects the catalog to be reachable without authentication;
    mount it outside any auth middleware.
    """
    app.router.routes.append(ai_catalog_route(catalog, path=path))
