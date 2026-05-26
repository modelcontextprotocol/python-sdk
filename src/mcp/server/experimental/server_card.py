"""Generate and serve MCP Server Cards (SEP-2127).

WARNING: These APIs are experimental and may change without notice.

A server author builds a card from the server's identity and either serves it
from the conventional ``.well-known`` path or hands it to their own Starlette
app::

    from mcp.server.experimental.server_card import build_server_card, mount_server_card
    from mcp.shared.experimental.server_card import Remote

    card = build_server_card(
        server,
        name="io.modelcontextprotocol.examples/dice-roller",
        remotes=[Remote(type="streamable-http", url="https://dice.example.com/mcp")],
    )

    app = server.streamable_http_app()
    mount_server_card(app, card)            # GET /.well-known/mcp/server-card

To write a card to a file instead, serialize it with
``card.model_dump_json(by_alias=True, exclude_none=True)``.
"""

from __future__ import annotations

from typing import Any, Protocol

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp.shared.experimental.server_card.types import (
    WELL_KNOWN_PATH,
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


def server_card_route(card: ServerCard, *, path: str = WELL_KNOWN_PATH) -> Route:
    """Build a Starlette GET route that serves ``card`` as JSON at ``path``.

    Add it to a new app — ``Starlette(routes=[server_card_route(card)])`` — or an
    existing one via :func:`mount_server_card`. The payload is serialized once;
    a card is static metadata.
    """
    payload = card.model_dump(mode="json", by_alias=True, exclude_none=True)

    async def endpoint(_request: Request) -> JSONResponse:
        return JSONResponse(payload, media_type="application/json")

    return Route(path, endpoint=endpoint, methods=["GET"], name="mcp_server_card")


def mount_server_card(app: Starlette, card: ServerCard, *, path: str = WELL_KNOWN_PATH) -> None:
    """Attach a Server Card route to an existing Starlette application.

    The route is unauthenticated, which is what pre-connection discovery wants.
    """
    app.router.routes.append(server_card_route(card, path=path))
