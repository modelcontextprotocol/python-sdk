"""Server-side generation and serving of MCP Server Cards.

A server author builds a :class:`~mcp_server_card.types.ServerCard` once (from
identity + remote endpoints), then either:

* hands it to the CLI / :func:`write_server_card` to publish a static file, or
* serves it from the conventional ``.well-known`` path via :func:`mount_server_card`
  (any Starlette app) or :func:`add_server_card_route` (an ``MCPServer``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .client import WELL_KNOWN_PATH
from .types import (
    SERVER_CARD_SCHEMA_URL,
    Icon,
    Remote,
    Repository,
    ServerCard,
)

__all__ = [
    "card_to_dict",
    "card_to_json",
    "build_server_card",
    "streamable_http_remote",
    "server_card_from_implementation",
    "write_server_card",
    "server_card_route",
    "mount_server_card",
    "add_server_card_route",
]


def card_to_dict(card: ServerCard) -> dict[str, Any]:
    """Serialize a card to a JSON-ready dict (camelCase keys, ``None`` dropped)."""
    return card.model_dump(mode="json", by_alias=True, exclude_none=True)


def card_to_json(card: ServerCard, *, indent: int | None = 2) -> str:
    """Serialize a card to a JSON string."""
    return card.model_dump_json(by_alias=True, exclude_none=True, indent=indent)


def build_server_card(
    *,
    name: str,
    version: str,
    description: str,
    title: str | None = None,
    website_url: str | None = None,
    repository: Repository | None = None,
    icons: list[Icon] | None = None,
    remotes: list[Remote] | None = None,
    meta: dict[str, Any] | None = None,
    schema_uri: str = SERVER_CARD_SCHEMA_URL,
) -> ServerCard:
    """Build (and validate) a Server Card from its parts.

    Construction runs the model's field validators, so an invalid ``name`` /
    ``version`` / ``description`` fails fast here rather than at publish time.
    """
    return ServerCard(
        schema_uri=schema_uri,
        name=name,
        version=version,
        description=description,
        title=title,
        website_url=website_url,
        repository=repository,
        icons=icons,
        remotes=remotes,
        meta=meta,
    )


def streamable_http_remote(
    url: str,
    *,
    headers: list[Any] | None = None,
    variables: dict[str, Any] | None = None,
    supported_protocol_versions: list[str] | None = None,
) -> Remote:
    """Convenience constructor for the common streamable-HTTP remote endpoint."""
    return Remote(
        type="streamable-http",
        url=url,
        headers=headers,
        variables=variables,
        supported_protocol_versions=supported_protocol_versions,
    )


class _ImplementationLike(Protocol):
    name: str
    version: str
    title: str | None
    description: str | None
    website_url: str | None
    icons: list[Icon] | None


def server_card_from_implementation(
    name: str,
    implementation: _ImplementationLike,
    *,
    remotes: list[Remote] | None = None,
    repository: Repository | None = None,
    meta: dict[str, Any] | None = None,
) -> ServerCard:
    """Build a card, pulling display/version metadata from an SDK ``Implementation``.

    ``Implementation.name`` is a free-form display name, while a card's ``name``
    must be reverse-DNS (``namespace/name``), so it is passed explicitly. The
    rest (version, title, description, website, icons) is carried over.
    """
    return build_server_card(
        name=name,
        version=implementation.version,
        description=implementation.description or (implementation.title or name),
        title=implementation.title,
        website_url=implementation.website_url,
        icons=implementation.icons,
        repository=repository,
        remotes=remotes,
        meta=meta,
    )


def write_server_card(card: ServerCard, path: str | Path, *, indent: int | None = 2) -> Path:
    """Write a card to ``path`` as JSON and return the resolved path.

    This is the primitive the CLI uses to publish a static card file.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(card_to_json(card, indent=indent) + "\n", encoding="utf-8")
    return out.resolve()


def server_card_route(card: ServerCard, *, path: str = WELL_KNOWN_PATH, name: str = "mcp_server_card") -> Route:
    """Build a Starlette GET route that serves ``card`` at ``path``.

    The payload is serialized once up front; the card is static metadata.
    """
    payload = card_to_dict(card)

    async def endpoint(_request: Request) -> JSONResponse:
        return JSONResponse(payload, media_type="application/json")

    return Route(path, endpoint=endpoint, methods=["GET"], name=name)


def mount_server_card(app: Starlette, card: ServerCard, *, path: str = WELL_KNOWN_PATH) -> None:
    """Attach a Server Card route to an existing Starlette application."""
    app.router.routes.append(server_card_route(card, path=path))


def add_server_card_route(mcp_server: Any, card: ServerCard, *, path: str = WELL_KNOWN_PATH) -> None:
    """Register a Server Card route on an ``MCPServer`` via its ``custom_route``.

    Duck-typed so the example doesn't hard-depend on the high-level server API.
    Routes added this way are unauthenticated, which is what discovery wants.
    """
    payload = card_to_dict(card)

    async def endpoint(_request: Request) -> JSONResponse:
        return JSONResponse(payload, media_type="application/json")

    mcp_server.custom_route(path, methods=["GET"])(endpoint)
