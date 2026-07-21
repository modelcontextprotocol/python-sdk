"""`mcp.server.experimental.server_card`: card building, discovery routes and mounts."""

from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from inline_snapshot import snapshot
from mcp_types import Icon
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request

from mcp.server import MCPServer, Server
from mcp.server.experimental.server_card import (
    build_server_card,
    catalog_identifier,
    create_ai_catalog_routes,
    create_server_card_routes,
    discovery_response,
    mount_ai_catalog,
    mount_discovery,
    mount_server_card,
    server_card_entry,
)
from mcp.shared.experimental.ai_catalog import AICatalog
from mcp.shared.experimental.server_card import Remote, Repository, ServerCard

pytestmark = pytest.mark.anyio

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _card() -> ServerCard:
    return ServerCard(
        name="com.example/weather",
        version="1.4.0",
        description="Hourly forecasts.",
        title="Weather",
        remotes=[Remote(type="streamable-http", url="https://mcp.example.com/mcp")],
    )


def _client_for(routes_app: Starlette) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=routes_app), base_url="https://mcp.example.com")


# -- build_server_card -------------------------------------------------------------------


def test_build_server_card_derives_identity_from_an_mcpserver() -> None:
    """SDK-defined: title, description, version, website URL and icons come from the
    server object, keeping the card consistent with runtime `serverInfo`."""
    server = MCPServer(
        name="Weather",
        title="Weather",
        version="1.4.0",
        description="Hourly forecasts.",
        website_url="https://example.com",
    )
    card = build_server_card(server, name="com.example/weather")
    assert card.model_dump(by_alias=True, exclude_none=True) == snapshot(
        {
            "$schema": "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json",
            "name": "com.example/weather",
            "version": "1.4.0",
            "description": "Hourly forecasts.",
            "title": "Weather",
            "websiteUrl": "https://example.com",
        }
    )


def test_build_server_card_derives_identity_from_a_lowlevel_server() -> None:
    """SDK-defined: the lowlevel `Server` satisfies the same identity surface as
    `MCPServer`, via plain attributes instead of properties."""
    server = Server("weather", version="2.0.0", description="Forecasts.", title="Weather")
    card = build_server_card(server, name="com.example/weather")
    assert (card.version, card.description, card.title) == ("2.0.0", "Forecasts.", "Weather")


def test_build_server_card_explicit_kwargs_override_derived_values() -> None:
    """SDK-defined: every explicit keyword argument beats the server-derived value, and
    `repository`/`icons` (never derivable from a server object) land on the card."""
    server = MCPServer(name="Weather", version="1.4.0", description="Hourly forecasts.")
    remotes = [Remote(type="streamable-http", url="https://mcp.example.com/mcp")]
    repository = Repository(url="https://github.com/example/weather", source="github")
    icons = [Icon(src="https://example.com/icon.png", mime_type="image/png", sizes=["48x48"])]
    card = build_server_card(
        server,
        name="com.example/weather",
        version="9.9.9",
        description="Overridden.",
        title="Custom",
        website_url="https://override.example.com",
        remotes=remotes,
        repository=repository,
        icons=icons,
        meta={"com.example/build": 7},
    )
    assert card.version == "9.9.9"
    assert card.description == "Overridden."
    assert card.title == "Custom"
    assert card.website_url == "https://override.example.com"
    assert card.remotes == remotes
    assert card.repository == repository
    assert card.icons == icons
    assert card.meta == {"com.example/build": 7}


def test_build_server_card_rejects_a_server_without_a_version() -> None:
    """SDK-defined: a card requires a version, so a server that has none and no
    `version=` override fails card validation."""
    server = MCPServer(name="Weather", description="Hourly forecasts.")
    with pytest.raises(ValidationError):
        build_server_card(server, name="com.example/weather")


def test_build_server_card_rejects_an_overlong_derived_description() -> None:
    """SDK-defined: the card's 100 character description cap applies to derived values
    too, surfacing as `pydantic.ValidationError`."""
    server = MCPServer(name="Weather", version="1.0.0", description="x" * 101)
    with pytest.raises(ValidationError):
        build_server_card(server, name="com.example/weather")


# -- serving the card --------------------------------------------------------------------


async def test_card_is_served_with_its_media_type_at_the_reserved_path() -> None:
    """Spec-mandated: the card lives at the streamable HTTP path plus `/server-card`
    and is served as `application/mcp-server-card+json`."""
    card = _card()
    async with _client_for(Starlette(routes=create_server_card_routes(card))) as client:
        response = await client.get("/mcp/server-card")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/mcp-server-card+json"
    assert ServerCard.model_validate_json(response.content) == card


async def test_card_responses_carry_the_three_cors_headers() -> None:
    """Spec-mandated MUST: `Access-Control-Allow-Origin: *`, `-Methods: GET` and
    `-Headers: Content-Type` on the card response."""
    async with _client_for(Starlette(routes=create_server_card_routes(_card()))) as client:
        response = await client.get("/mcp/server-card")
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-methods"] == "GET"
    assert response.headers["access-control-allow-headers"] == "Content-Type"


async def test_card_responses_carry_the_default_cache_control() -> None:
    """Spec-mandated SHOULD: hosts send caching headers, defaulting to the spec's
    example of one hour."""
    async with _client_for(Starlette(routes=create_server_card_routes(_card()))) as client:
        response = await client.get("/mcp/server-card")
    assert response.headers["cache-control"] == "public, max-age=3600"


async def test_options_preflight_returns_the_cors_headers_and_no_body() -> None:
    """SDK-defined: a bare OPTIONS gets 200 with the CORS headers and an empty body."""
    async with _client_for(Starlette(routes=create_server_card_routes(_card()))) as client:
        response = await client.options("/mcp/server-card")
    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["access-control-allow-origin"] == "*"


async def test_browser_preflight_through_the_cors_middleware_is_allowed() -> None:
    """Spec-mandated: a real browser preflight (Origin plus requested method) succeeds
    and advertises GET as the only allowed method, so web-based hosts can fetch the card
    cross-origin. Starlette answers this one, not `discovery_response`."""
    async with _client_for(Starlette(routes=create_server_card_routes(_card()))) as client:
        response = await client.options(
            "/mcp/server-card",
            headers={"Origin": "https://host.example.org", "Access-Control-Request-Method": "GET"},
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-methods"] == "GET"


# -- ETag / If-None-Match ----------------------------------------------------------------


async def test_etag_is_strong_and_stable_across_requests() -> None:
    """SDK-defined (spec issue #33): every 200 carries a strong SHA-256 ETag that does
    not change while the card does not."""
    async with _client_for(Starlette(routes=create_server_card_routes(_card()))) as client:
        first = await client.get("/mcp/server-card")
        second = await client.get("/mcp/server-card")
    etag = first.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"')
    assert second.headers["etag"] == etag


def _exact_tag(tag: str) -> str:
    return tag


def _weak_tag(tag: str) -> str:
    return f"W/{tag}"


def _star_tag(tag: str) -> str:
    return "*"


def _list_member_tag(tag: str) -> str:
    return f'"nope", {tag}'


@pytest.mark.parametrize(
    "wrap",
    [_exact_tag, _weak_tag, _star_tag, _list_member_tag],
    ids=["exact", "weak", "star", "list-member"],
)
async def test_matching_if_none_match_returns_304_with_headers(wrap: Callable[[str], str]) -> None:
    """SDK-defined (spec issue #33): the exact tag, its weak form, `*` and a list member
    all revalidate to an empty 304 that keeps the ETag, CORS and caching headers."""
    async with _client_for(Starlette(routes=create_server_card_routes(_card()))) as client:
        first = await client.get("/mcp/server-card")
        etag = first.headers["etag"]
        response = await client.get("/mcp/server-card", headers={"If-None-Match": wrap(etag)})
    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["etag"] == etag
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["cache-control"] == "public, max-age=3600"


async def test_non_matching_if_none_match_returns_the_full_card() -> None:
    """SDK-defined: a stale ETag misses and the full 200 comes back."""
    async with _client_for(Starlette(routes=create_server_card_routes(_card()))) as client:
        response = await client.get("/mcp/server-card", headers={"If-None-Match": '"stale"'})
    assert response.status_code == 200
    assert response.content != b""


# -- path resolution and cache control knobs ----------------------------------------------


async def test_card_path_follows_the_streamable_http_path() -> None:
    """Spec-mandated: the reserved suffix anchors to the transport path, not the domain
    root, and a trailing slash on the transport path does not double up."""
    routes = create_server_card_routes(_card(), streamable_http_path="/api/mcp/")
    assert [route.path for route in routes] == ["/api/mcp/server-card"]


async def test_explicit_path_overrides_the_reserved_location() -> None:
    """Spec-mandated: a card MAY be hosted at any unreserved URI."""
    routes = create_server_card_routes(_card(), path="/cards/weather.json")
    assert [route.path for route in routes] == ["/cards/weather.json"]


async def test_cache_control_override_and_empty_string_omission() -> None:
    """SDK-defined: `discovery_response`'s `cache_control` is tunable through custom
    handlers; the built-in routes always use the default. An empty string omits the
    header entirely."""
    scope: dict[str, Any] = {"type": "http", "method": "GET", "headers": [], "query_string": b"", "path": "/c"}
    tuned = discovery_response(Request(scope), b"{}", "application/json", cache_control="public, max-age=60")
    assert tuned.headers["cache-control"] == "public, max-age=60"
    omitted = discovery_response(Request(scope), b"{}", "application/json", cache_control="")
    assert "cache-control" not in omitted.headers


# -- the catalog routes --------------------------------------------------------------------


async def test_catalog_is_served_at_the_well_known_path_with_its_media_type() -> None:
    """Spec-mandated: domain-level discovery reads `/.well-known/ai-catalog.json` served
    as `application/ai-catalog+json`, with the same CORS and caching headers."""
    catalog = AICatalog(spec_version="1.0", entries=[server_card_entry(_card(), publisher="example.com")])
    async with _client_for(Starlette(routes=create_ai_catalog_routes(catalog))) as client:
        response = await client.get("/.well-known/ai-catalog.json")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/ai-catalog+json"
    assert response.headers["access-control-allow-origin"] == "*"
    assert AICatalog.model_validate_json(response.content) == catalog


# -- catalog_identifier and server_card_entry ----------------------------------------------


def test_catalog_identifier_includes_the_mcp_namespace_segment() -> None:
    """Spec-mandated: the URN is `urn:air:{publisher}:mcp:{name}` for card
    `com.example/weather` published by example.com."""
    assert catalog_identifier("com.example/weather", publisher="example.com") == "urn:air:example.com:mcp:weather"


def test_catalog_identifier_rejects_a_name_without_a_namespace() -> None:
    """SDK-defined: a card name outside the `namespace/name` pattern has no URN."""
    with pytest.raises(ValueError, match="namespace/name"):
        catalog_identifier("weather", publisher="example.com")


def test_server_card_entry_with_url_points_at_the_hosted_card() -> None:
    """Spec-mandated: a URL entry carries the card's media type and does not duplicate
    the card's fields beyond `displayName`."""
    entry = server_card_entry(_card(), publisher="example.com", url="https://mcp.example.com/mcp/server-card")
    assert entry.model_dump(by_alias=True, exclude_none=True) == snapshot(
        {
            "identifier": "urn:air:example.com:mcp:weather",
            "type": "application/mcp-server-card+json",
            "url": "https://mcp.example.com/mcp/server-card",
            "displayName": "Weather",
        }
    )


def test_server_card_entry_without_url_inlines_the_full_card() -> None:
    """Spec-mandated: `url=None` inlines the card as the entry's `data`, and the inline
    document parses back to the same card."""
    card = _card()
    entry = server_card_entry(card, publisher="example.com")
    assert entry.url is None
    assert ServerCard.model_validate(entry.data) == card


def test_server_card_entry_honors_an_explicit_identifier() -> None:
    """SDK-defined: a caller-chosen identifier wins over the derived URN."""
    entry = server_card_entry(_card(), publisher="example.com", identifier="urn:air:example.com:custom:weather")
    assert entry.identifier == "urn:air:example.com:custom:weather"


@pytest.mark.parametrize("url", ["/mcp/server-card", "http://mcp.example.com/mcp/server-card"])
def test_server_card_entry_rejects_relative_and_insecure_urls(url: str) -> None:
    """Spec-mandated: catalogs are fetched cross-domain, so entry URLs must be absolute,
    and production transport must be HTTPS."""
    with pytest.raises(ValueError, match="URL|loopback"):
        server_card_entry(_card(), publisher="example.com", url=url)


def test_server_card_entry_allows_plain_http_to_loopback() -> None:
    """SDK-defined: plain http stays available for local development."""
    entry = server_card_entry(_card(), publisher="localhost", url="http://localhost:8000/mcp/server-card")
    assert entry.url == "http://localhost:8000/mcp/server-card"


# -- mounting on a built app ----------------------------------------------------------------


async def test_mount_discovery_serves_both_endpoints_beside_a_live_transport() -> None:
    """Spec-mandated end to end: after `mount_discovery` on `streamable_http_app()`, the
    card, the catalog and the MCP transport all answer on one app, and the catalog entry
    points at the card's absolute URL."""
    server = MCPServer(name="Weather", version="1.4.0", description="Hourly forecasts.")
    app = server.streamable_http_app()
    card = build_server_card(
        server,
        name="com.example/weather",
        remotes=[Remote(type="streamable-http", url="https://mcp.example.com/mcp")],
    )
    mount_discovery(app, card, public_url="https://mcp.example.com")

    transport = httpx2.ASGITransport(app=app)
    async with server.session_manager.run():
        # The default transport security allows `localhost:*` hosts only, which is
        # fine here: the discovery routes carry no host restriction.
        async with httpx2.AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
            initialize = await client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
            card_response = await client.get("/mcp/server-card")
            catalog_response = await client.get("/.well-known/ai-catalog.json")
    assert initialize.status_code == 200
    assert ServerCard.model_validate_json(card_response.content) == card
    catalog = AICatalog.model_validate_json(catalog_response.content)
    assert catalog.entries[0].url == "https://mcp.example.com/mcp/server-card"
    assert catalog.entries[0].identifier == "urn:air:mcp.example.com:mcp:weather"


async def test_mount_server_card_and_mount_ai_catalog_append_routes_independently() -> None:
    """SDK-defined: the single-purpose mounts add exactly their own endpoint to an
    existing app."""
    app = Starlette()
    mount_server_card(app, _card(), streamable_http_path="/api/mcp")
    mount_ai_catalog(app, AICatalog(spec_version="1.0", entries=[]), path="/catalog.json")
    async with _client_for(app) as client:
        card_response = await client.get("/api/mcp/server-card")
        catalog_response = await client.get("/catalog.json")
    assert card_response.status_code == 200
    assert catalog_response.status_code == 200


@pytest.mark.parametrize("public_url", ["http://mcp.example.com", "example.com/mcp", "ftp://mcp.example.com"])
def test_mount_discovery_rejects_insecure_or_relative_public_urls(public_url: str) -> None:
    """Spec-mandated: HTTPS is a MUST in production, so `public_url` must be absolute
    http(s) and plain http is loopback-only."""
    with pytest.raises(ValueError, match="URL|loopback"):
        mount_discovery(Starlette(), _card(), public_url=public_url)


async def test_mount_discovery_allows_plain_http_to_loopback() -> None:
    """SDK-defined: local development mounts against `http://localhost` work."""
    app = Starlette()
    mount_discovery(app, _card(), public_url="http://localhost:8000")
    async with _client_for(app) as client:
        response = await client.get("/.well-known/ai-catalog.json")
    entry = AICatalog.model_validate_json(response.content).entries[0]
    assert entry.url == "http://localhost:8000/mcp/server-card"
