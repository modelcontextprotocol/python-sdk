"""Tests for server-side AI Catalog generation and serving."""

import re

import httpx2
import pytest
from starlette.applications import Starlette

from mcp.server.experimental.ai_catalog import ai_catalog_route, mount_ai_catalog, server_card_entry
from mcp.shared.experimental.ai_catalog import AICatalog
from mcp.shared.experimental.server_card import ServerCard

pytestmark = pytest.mark.anyio

CARD_URL = "https://dice.example.com/server-card.json"


def make_card(title: str | None = None) -> ServerCard:
    return ServerCard(name="example/dice", version="1.0.0", description="Rolls dice.", title=title)


def test_server_card_entry_emits_minimal_mcp_entry() -> None:
    entry = server_card_entry(make_card(title="Dice Roller"), CARD_URL)
    assert entry.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "identifier": "urn:air:example:mcp:dice",
        "type": "application/mcp-server-card+json",
        "url": CARD_URL,
    }


def test_server_card_entry_reverses_namespace_to_publisher_domain() -> None:
    """The identifier is anchored on the publisher's forward-DNS domain."""
    card = ServerCard(name="com.example/weather", version="1.0.0", description="Weather.")
    assert server_card_entry(card, CARD_URL).identifier == "urn:air:example.com:mcp:weather"


async def _get(app: Starlette, path: str, headers: dict[str, str] | None = None) -> httpx2.Response:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://dice.example.com") as client:
        return await client.get(path, headers=headers)


async def _head(app: Starlette, path: str) -> httpx2.Response:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://dice.example.com") as client:
        return await client.head(path)


async def test_ai_catalog_route_serves_catalog_with_discovery_headers() -> None:
    catalog = AICatalog(spec_version="1.0", entries=[server_card_entry(make_card(), CARD_URL)])
    app = Starlette(routes=[ai_catalog_route(catalog)])
    response = await _get(app, "/.well-known/ai-catalog.json")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/ai-catalog+json"
    # Discovery requires CORS headers (MUST) and caching headers (SHOULD).
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-methods"] == "GET"
    assert response.headers["access-control-allow-headers"] == "Content-Type"
    assert response.headers["cache-control"] == "public, max-age=3600"
    etag = response.headers["etag"]
    assert re.fullmatch(r'"[0-9a-f]{64}"', etag)
    assert (await _get(app, "/.well-known/ai-catalog.json")).headers["etag"] == etag
    assert (await _head(app, "/.well-known/ai-catalog.json")).headers["etag"] == etag
    assert response.text == catalog.model_dump_json(by_alias=True, exclude_none=True)

    not_modified = await _get(app, "/.well-known/ai-catalog.json", headers={"If-None-Match": etag})
    assert not_modified.status_code == 304
    assert not_modified.headers["etag"] == etag
    assert not_modified.headers["access-control-allow-origin"] == "*"
    assert not_modified.headers["access-control-allow-methods"] == "GET"
    assert not_modified.headers["access-control-allow-headers"] == "Content-Type"
    assert not_modified.headers["cache-control"] == "public, max-age=3600"
    assert not_modified.content == b""

    weak_match = await _get(app, "/.well-known/ai-catalog.json", headers={"If-None-Match": f'"not-it", W/{etag}'})
    assert weak_match.status_code == 304
    assert weak_match.content == b""

    wildcard = await _get(app, "/.well-known/ai-catalog.json", headers={"If-None-Match": "*"})
    assert wildcard.status_code == 304
    assert wildcard.headers["etag"] == etag
    assert wildcard.content == b""

    non_matching = await _get(app, "/.well-known/ai-catalog.json", headers={"If-None-Match": '"not-it"'})
    assert non_matching.status_code == 200
    assert non_matching.headers["etag"] == etag
    assert non_matching.text == catalog.model_dump_json(by_alias=True, exclude_none=True)


async def test_mount_ai_catalog_on_existing_app() -> None:
    app = Starlette()
    mount_ai_catalog(app, AICatalog(spec_version="1.0", entries=[]))
    response = await _get(app, "/.well-known/ai-catalog.json")
    assert response.status_code == 200
    assert AICatalog.model_validate(response.json()) == AICatalog(spec_version="1.0", entries=[])


async def test_mount_ai_catalog_custom_path() -> None:
    app = Starlette()
    mount_ai_catalog(app, AICatalog(spec_version="1.0", entries=[]), path="/catalog.json")
    response = await _get(app, "/catalog.json")
    assert response.status_code == 200
