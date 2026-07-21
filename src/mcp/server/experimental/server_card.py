"""Serve a Server Card and an AI Catalog over HTTP (experimental, tracks SEP-2127).

The route builders return plain Starlette routes, so they compose with
`streamable_http_app()` or any ASGI application. Every response goes through
`discovery_response`, the single enforcement point for the discovery spec's
HTTP requirements: media type, CORS, caching headers and conditional requests.

Mount these routes outside any auth middleware. Discovery is unauthenticated
by design, and a card or catalog MUST NOT contain credentials, internal
network topology or private endpoints.
"""

import hashlib
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol
from urllib.parse import urlsplit

from mcp_types import Icon
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route, request_response
from starlette.types import ASGIApp

from mcp.shared.experimental._base import SERVER_CARD_NAME_PATTERN, is_loopback_host
from mcp.shared.experimental.ai_catalog import (
    AI_CATALOG_MEDIA_TYPE,
    AI_CATALOG_WELL_KNOWN_PATH,
    AICatalog,
    CatalogEntry,
)
from mcp.shared.experimental.server_card import (
    RESERVED_SERVER_CARD_SUFFIX,
    SERVER_CARD_MEDIA_TYPE,
    Remote,
    Repository,
    ServerCard,
)

__all__ = [
    "build_server_card",
    "create_server_card_routes",
    "mount_server_card",
    "create_ai_catalog_routes",
    "mount_ai_catalog",
    "mount_discovery",
    "server_card_entry",
    "catalog_identifier",
    "discovery_response",
]

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET",
    "Access-Control-Allow-Headers": "Content-Type",
}


class _ServerIdentity(Protocol):
    """The identity surface `build_server_card` reads.

    Both `MCPServer` (properties) and the lowlevel `Server` (plain attributes)
    satisfy this structurally.
    """

    @property
    def name(self) -> str: ...
    @property
    def title(self) -> str | None: ...
    @property
    def version(self) -> str | None: ...
    @property
    def description(self) -> str | None: ...
    @property
    def website_url(self) -> str | None: ...
    @property
    def icons(self) -> list[Icon] | None: ...


def build_server_card(
    server: _ServerIdentity,
    *,
    name: str,
    remotes: Sequence[Remote] | None = None,
    repository: Repository | None = None,
    description: str | None = None,
    title: str | None = None,
    version: str | None = None,
    website_url: str | None = None,
    icons: Sequence[Icon] | None = None,
    meta: dict[str, Any] | None = None,
) -> ServerCard:
    """Build a `ServerCard` from a server's identity fields.

    Title, description, version, website URL and icons come from the server
    object. Explicit keyword arguments override the derived values, which
    keeps the card consistent with what `serverInfo` reports at runtime. The
    namespaced `name` and the public `remotes` URLs are never derivable, so
    the caller supplies them.

    Raises:
        pydantic.ValidationError: If the result violates a card constraint,
            for example a server description over 100 characters or a version
            that is unset and not overridden.
    """
    resolved_icons = list(icons) if icons is not None else server.icons
    fields: dict[str, Any] = {
        "name": name,
        "version": version if version is not None else server.version,
        "description": description if description is not None else server.description,
        "title": title if title is not None else server.title,
        "website_url": website_url if website_url is not None else server.website_url,
        "icons": resolved_icons,
        "repository": repository,
        "remotes": list(remotes) if remotes is not None else None,
        "meta": meta,
    }
    return ServerCard.model_validate(fields)


def discovery_response(
    request: Request,
    body: bytes,
    media_type: str,
    *,
    cache_control: str = "public, max-age=3600",
) -> Response:
    """Answer one discovery request (card or catalog) per the extension spec.

    This is the compliance chokepoint the built-in routes use. It is public so
    custom hosting (FastAPI apps, non-default paths, multi-card hosts) can
    stay compliant. It emits the CORS headers the spec requires on every
    response, a `Cache-Control` header (pass `cache_control=""` to omit it), a
    strong SHA-256 `ETag`, a `304 Not Modified` for a matching
    `If-None-Match`, and an empty 200 for `OPTIONS` preflight.
    """
    headers = dict(_CORS_HEADERS)
    if request.method == "OPTIONS":
        return Response(status_code=200, headers=headers)
    if cache_control:
        headers["Cache-Control"] = cache_control
    etag = '"' + hashlib.sha256(body).hexdigest() + '"'
    headers["ETag"] = etag
    if _if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type=media_type, headers=headers)


def _if_none_match_matches(header_value: str | None, etag: str) -> bool:
    """Whether an `If-None-Match` header matches a strong ETag.

    Accepts the exact strong tag, its `W/`-prefixed weak form, `*`, or any
    member of a comma-separated list.
    """
    if header_value is None:
        return False
    for candidate in header_value.split(","):
        stripped = candidate.strip()
        if stripped == "*" or stripped.removeprefix("W/") == etag:
            return True
    return False


def _cors_endpoint(handler: Callable[[Request], Awaitable[Response]]) -> ASGIApp:
    """Wrap a handler with `CORSMiddleware`, belt and braces over the explicit headers.

    The middleware short-circuits real browser preflights (OPTIONS with an
    `Origin` and a requested method), answering with `GET` as the only allowed
    method; Starlette also advertises the CORS-safelisted request headers
    beside `Content-Type` there, a valid superset of the spec's example. A
    bare OPTIONS still reaches `discovery_response`.
    """
    return CORSMiddleware(
        app=request_response(handler),
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
    )


def _document_routes(path: str, body: bytes, media_type: str) -> list[Route]:
    """GET and OPTIONS routes serving one static discovery document."""

    async def handler(request: Request) -> Response:
        return discovery_response(request, body, media_type)

    return [Route(path, endpoint=_cors_endpoint(handler), methods=["GET", "OPTIONS"])]


def create_server_card_routes(
    card: ServerCard,
    *,
    streamable_http_path: str = "/mcp",
    path: str | None = None,
) -> list[Route]:
    """Routes serving `card` at the spec-reserved path.

    The default path is the streamable HTTP path plus `/server-card`, for
    example `/mcp/server-card`. Pass `path` to host the card at any other
    unreserved URI instead.
    """
    resolved_path = path if path is not None else streamable_http_path.rstrip("/") + RESERVED_SERVER_CARD_SUFFIX
    body = card.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")
    return _document_routes(resolved_path, body, SERVER_CARD_MEDIA_TYPE)


def create_ai_catalog_routes(catalog: AICatalog, *, path: str = AI_CATALOG_WELL_KNOWN_PATH) -> list[Route]:
    """Routes serving `catalog`, by default at the well-known discovery path."""
    body = catalog.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")
    return _document_routes(path, body, AI_CATALOG_MEDIA_TYPE)


def mount_server_card(
    app: Starlette,
    card: ServerCard,
    *,
    streamable_http_path: str = "/mcp",
    path: str | None = None,
) -> None:
    """Append the card routes to an already-built app.

    Works on the result of `streamable_http_app()`. Mount outside any auth
    middleware. Discovery is unauthenticated by design.
    """
    app.router.routes.extend(create_server_card_routes(card, streamable_http_path=streamable_http_path, path=path))


def mount_ai_catalog(app: Starlette, catalog: AICatalog, *, path: str = AI_CATALOG_WELL_KNOWN_PATH) -> None:
    """Append the catalog routes to an already-built app."""
    app.router.routes.extend(create_ai_catalog_routes(catalog, path=path))


def _require_public_http_url(url: str) -> str:
    """Validate an absolute http(s) URL and return its host.

    Raises:
        ValueError: If `url` is not absolute http(s), or uses plain http to a
            host that is not loopback. The spec requires HTTPS in production.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"expected an absolute http(s) URL, got {url!r}")
    if parts.scheme == "http" and not is_loopback_host(parts.hostname):
        raise ValueError(f"plain http is only allowed for loopback hosts, got {url!r}")
    return parts.hostname


def catalog_identifier(card_name: str, *, publisher: str) -> str:
    """The recommended catalog URN for a card name.

    `catalog_identifier("com.example/weather", publisher="example.com")`
    returns `"urn:air:example.com:mcp:weather"`. The `mcp` namespace segment
    comes from the discovery spec.

    Raises:
        ValueError: If `card_name` does not match the `namespace/name` pattern.
    """
    if re.fullmatch(SERVER_CARD_NAME_PATTERN, card_name) is None:
        raise ValueError(f"card name must be namespace/name, got {card_name!r}")
    local_name = card_name.split("/", 1)[1]
    return f"urn:air:{publisher}:mcp:{local_name}"


def server_card_entry(
    card: ServerCard,
    *,
    publisher: str,
    url: str | None = None,
    identifier: str | None = None,
) -> CatalogEntry:
    """A `CatalogEntry` advertising `card`.

    With `url` the entry points at the hosted card. With `url=None` the full
    card is inlined as the entry's `data`. The identifier defaults to
    `catalog_identifier(card.name, publisher=publisher)`. Display fields are
    not duplicated from the card beyond `displayName`. Clients read title,
    description and version from the card itself.

    Raises:
        ValueError: If `url` is relative, or plain http to a non-loopback host.
    """
    resolved_identifier = identifier if identifier is not None else catalog_identifier(card.name, publisher=publisher)
    if url is None:
        data = card.model_dump(by_alias=True, exclude_none=True, mode="json")
        return CatalogEntry(
            identifier=resolved_identifier, type=SERVER_CARD_MEDIA_TYPE, data=data, display_name=card.title
        )
    _require_public_http_url(url)
    return CatalogEntry(identifier=resolved_identifier, type=SERVER_CARD_MEDIA_TYPE, url=url, display_name=card.title)


def mount_discovery(
    app: Starlette,
    card: ServerCard,
    *,
    public_url: str,
    streamable_http_path: str = "/mcp",
) -> None:
    """Mount both discovery endpoints on a single-domain deployment.

    Serves the card at the reserved path under `streamable_http_path` and a
    single-entry AI Catalog at the well-known path. The catalog entry's URL is
    absolute (catalogs are fetched cross-domain) and the entry's URN publisher
    is the host of `public_url`.

    `public_url` is the externally visible base URL at which `app`'s root is
    served, typically just the origin (`https://mcp.example.com`). Include a
    path only when a reverse proxy really serves the app under that prefix,
    because the catalog entry's URL is `public_url` plus the card path while
    the routes themselves are mounted at the app root; a `public_url` carrying
    a path that the proxy does not strip advertises a card URL that 404s.

    Per the best-practices guidance, the catalog belongs on the domain users
    associate with the service, which may not be the API app. In that case use
    `server_card_entry` to build an entry for the catalog on your brand
    domain instead.

    Raises:
        ValueError: If `public_url` is not absolute http(s), or is plain http
            to a non-loopback host.
    """
    publisher = _require_public_http_url(public_url)
    card_path = streamable_http_path.rstrip("/") + RESERVED_SERVER_CARD_SUFFIX
    entry = server_card_entry(card, publisher=publisher, url=public_url.rstrip("/") + card_path)
    mount_server_card(app, card, streamable_http_path=streamable_http_path)
    mount_ai_catalog(app, AICatalog(spec_version="1.0", entries=[entry]))
