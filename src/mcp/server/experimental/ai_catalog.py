"""Generate and serve AI Catalogs.

WARNING: These APIs are experimental and may change without notice.

A server advertises its MCP server(s) by serving an AI Catalog from the
well-known path, with one entry per Server Card::

    catalog = AICatalog(
        spec_version="1.0",
        entries=[server_card_entry(card, "https://example.com/server-card")],
    )
    mount_ai_catalog(server.streamable_http_app(), catalog)   # GET /.well-known/ai-catalog.json

To write a catalog to a file instead, use
``catalog.model_dump_json(by_alias=True, exclude_none=True)``.
"""

from __future__ import annotations

import hashlib

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from mcp.shared.experimental.ai_catalog.types import (
    AI_CATALOG_MEDIA_TYPE,
    AI_CATALOG_URN_PREFIX,
    AI_CATALOG_WELL_KNOWN_PATH,
    MCP_SERVER_CARD_MEDIA_TYPE,
    AICatalog,
    CatalogEntry,
)
from mcp.shared.experimental.server_card.types import ServerCard

__all__ = ["DISCOVERY_HEADERS", "server_card_entry", "ai_catalog_route", "mount_ai_catalog"]

#: Response headers for discovery endpoints (catalogs and the artifacts they
#: reference): CORS headers so browser clients can read them, plus a caching
#: hint.
DISCOVERY_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "public, max-age=3600",
}


def _if_none_match_matches(if_none_match: str | None, etag: str) -> bool:
    if if_none_match is None:
        return False
    for candidate in if_none_match.split(","):
        candidate = candidate.strip()
        if candidate == "*":
            return True
        if candidate.startswith(("W/", "w/")):
            candidate = candidate[2:].strip()
        if candidate == etag:
            return True
    return False


def discovery_response(request: Request, body: bytes, media_type: str) -> Response:
    """Build a cacheable discovery response with conditional ETag handling."""
    etag = f'"{hashlib.sha256(body).hexdigest()}"'
    if _if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(
            status_code=304,
            headers={**DISCOVERY_HEADERS, "ETag": etag},
        )
    return Response(body, media_type=media_type, headers={**DISCOVERY_HEADERS, "ETag": etag})


def _air_identifier(card_name: str) -> str:
    """Derive an AI Catalog ``urn:air:`` identifier from a Server Card name.

    The card ``name`` is ``namespace/suffix`` in reverse-DNS form
    (``com.example/weather``); the namespace labels are reversed to forward-DNS
    (``com.example`` -> ``example.com``) and the suffix appended:
    ``urn:air:example.com:mcp:weather``.
    """
    namespace, _, suffix = card_name.partition("/")
    publisher = ".".join(reversed(namespace.split(".")))
    return f"{AI_CATALOG_URN_PREFIX}{publisher}:mcp:{suffix}"


def server_card_entry(card: ServerCard, url: str) -> CatalogEntry:
    """Build the catalog entry advertising ``card``, served at ``url``.

    The entry's identifier is derived from the card's ``name``
    (``urn:air:{publisher}:mcp:{name}``). Human-readable fields stay on the
    Server Card so the catalog cannot drift from it. ``url`` should be the
    absolute URL the card is retrievable from, since catalogs may be fetched
    cross-domain.
    """
    return CatalogEntry(
        identifier=_air_identifier(card.name),
        media_type=MCP_SERVER_CARD_MEDIA_TYPE,
        url=url,
    )


def ai_catalog_route(catalog: AICatalog, *, path: str = AI_CATALOG_WELL_KNOWN_PATH) -> Route:
    """Build a Starlette GET route that serves ``catalog`` at ``path``.

    Add it to a new app — ``Starlette(routes=[ai_catalog_route(catalog)])`` —
    or an existing one via :func:`mount_ai_catalog`. The payload is serialized
    once and served with the CORS and caching headers discovery requires.
    """
    body = catalog.model_dump_json(by_alias=True, exclude_none=True).encode()

    async def endpoint(request: Request) -> Response:
        return discovery_response(request, body, AI_CATALOG_MEDIA_TYPE)

    return Route(path, endpoint=endpoint, methods=["GET"], name="ai_catalog")


def mount_ai_catalog(app: Starlette, catalog: AICatalog, *, path: str = AI_CATALOG_WELL_KNOWN_PATH) -> None:
    """Attach an AI Catalog route to an existing Starlette application.

    Discovery expects the catalog to be reachable without authentication;
    mount it outside any auth middleware.
    """
    app.router.routes.append(ai_catalog_route(catalog, path=path))
