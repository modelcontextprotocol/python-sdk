"""Generate and serve MCP Server Cards (SEP-2127).

WARNING: These APIs are experimental and may change without notice.

A server author builds a card from the server's identity and serves it. The
recommended location is ``<streamable-http-url>/server-card`` — pass ``path`` to
match the MCP endpoint (e.g. ``/mcp/server-card`` when the server is mounted at
``/mcp``)::

    card = build_server_card(server, name="com.example/dice-roller", remotes=[...])
    mount_server_card(server.streamable_http_app(), card, path="/mcp/server-card")

Clients learn the card's URL from a catalog entry, so any reachable path works;
the convention only matters for fallback probing.

A hosted card is only discoverable once it is registered in an AI Catalog (see
``mcp.server.experimental.ai_catalog``); clients learn a card's URL from a
catalog entry rather than guessing it. To write a card to a file instead of
serving it, use ``card.model_dump_json(by_alias=True, exclude_none=True)``.
"""

from __future__ import annotations

from typing import Any, Protocol

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from mcp.server.experimental.ai_catalog import DISCOVERY_HEADERS
from mcp.shared.experimental.ai_catalog.types import MCP_SERVER_CARD_MEDIA_TYPE
from mcp.shared.experimental.server_card.types import (
    Icon,
    Remote,
    Repository,
    ServerCard,
)

__all__ = ["build_server_card", "server_card_route", "mount_server_card"]


class _ServerIdentity(Protocol):
    """The identity attributes shared by the low-level ``Server`` and ``MCPServer``."""

    name: str
    version: str | None
    title: str | None
    description: str | None
    website_url: str | None
    icons: list[Icon] | None


def build_server_card(
    server: _ServerIdentity,
    *,
    name: str,
    remotes: list[Remote] | None = None,
    repository: Repository | None = None,
    meta: dict[str, Any] | None = None,
) -> ServerCard:
    """Build a Server Card from a running server's identity metadata.

    ``name`` is the card's reverse-DNS ``namespace/name`` identifier, passed
    explicitly because a server's display ``name`` is free-form. The version,
    title, description, website and icons are taken from ``server``.

    Args:
        server: A low-level ``Server`` or high-level ``MCPServer`` (anything
            exposing the standard identity attributes).
        name: Reverse-DNS server name, e.g. ``"io.modelcontextprotocol/everything"``.
        remotes: Remote endpoints to advertise.
        repository: Optional source repository metadata.
        meta: Optional ``_meta`` extension metadata.

    Returns:
        A validated :class:`ServerCard`.

    Raises:
        ValueError: If ``server`` has no ``version`` or ``description`` set; both
            are required on a card.
        pydantic.ValidationError: If the resulting card is invalid (e.g. ``name``
            is not reverse-DNS).
    """
    if server.version is None:
        raise ValueError("server.version must be set to build a Server Card")
    if not server.description:
        raise ValueError("server.description must be set to build a Server Card")
    return ServerCard(
        name=name,
        version=server.version,
        description=server.description,
        title=server.title,
        website_url=server.website_url,
        icons=server.icons,
        remotes=remotes,
        repository=repository,
        _meta=meta,
    )


def server_card_route(card: ServerCard, *, path: str = "/server-card") -> Route:
    """Build a Starlette GET route that serves ``card`` at ``path``.

    ``path`` defaults to ``/server-card``, the recommended location
    (``<streamable-http-url>/server-card``). Add the route to
    a new app — ``Starlette(routes=[server_card_route(card)])`` — or an existing
    one via :func:`mount_server_card`, and advertise the resulting URL in an AI
    Catalog entry. The payload is serialized once and served as
    ``application/mcp-server-card+json`` with the CORS and caching headers
    discovery requires.
    """
    body = card.model_dump_json(by_alias=True, exclude_none=True).encode()

    async def endpoint(_request: Request) -> Response:
        return Response(body, media_type=MCP_SERVER_CARD_MEDIA_TYPE, headers=DISCOVERY_HEADERS)

    return Route(path, endpoint=endpoint, methods=["GET"], name="mcp_server_card")


def mount_server_card(app: Starlette, card: ServerCard, *, path: str = "/server-card") -> None:
    """Attach a Server Card route to an existing Starlette application.

    ``path`` defaults to ``/server-card``, the reserved location. Pre-connection
    discovery expects the card to be reachable without authentication; mount it
    outside any auth middleware.
    """
    app.router.routes.append(server_card_route(card, path=path))
