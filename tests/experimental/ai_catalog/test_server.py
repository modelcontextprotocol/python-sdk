"""Tests for server-side AI Catalog generation and serving."""

from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette

from mcp.server.experimental.ai_catalog import ai_catalog_route, mount_ai_catalog, server_card_entry
from mcp.shared.experimental.ai_catalog import AICatalog
from mcp.shared.experimental.server_card import ServerCard

pytestmark = pytest.mark.anyio

CARD_URL = "https://dice.example.com/server-card.json"


def make_card(title: str | None = None) -> ServerCard:
    return ServerCard(name="example/dice", version="1.0.0", description="Rolls dice.", title=title)


def test_server_card_entry_derives_identifier_and_metadata_from_card() -> None:
    entry = server_card_entry(make_card(title="Dice Roller"), CARD_URL)
    assert entry.identifier == "urn:air:example:dice"
    assert entry.display_name == "Dice Roller"
    assert entry.media_type == "application/mcp-server-card+json"
    assert entry.url == CARD_URL
    assert entry.description == "Rolls dice."
    assert entry.version == "1.0.0"


def test_server_card_entry_reverses_namespace_to_publisher_domain() -> None:
    """The identifier is anchored on the publisher's forward-DNS domain."""
    card = ServerCard(name="com.example/weather", version="1.0.0", description="Weather.")
    assert server_card_entry(card, CARD_URL).identifier == "urn:air:example.com:weather"


def test_server_card_entry_falls_back_to_card_name_without_title() -> None:
    assert server_card_entry(make_card(), CARD_URL).display_name == "example/dice"


async def _get(app: Starlette, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://dice.example.com") as client:
        return await client.get(path)


async def test_ai_catalog_route_serves_catalog_with_discovery_headers() -> None:
    catalog = AICatalog(entries=[server_card_entry(make_card(), CARD_URL)])
    app = Starlette(routes=[ai_catalog_route(catalog)])
    response = await _get(app, "/.well-known/ai-catalog.json")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/ai-catalog+json"
    # Discovery requires CORS headers (MUST) and caching headers (SHOULD).
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-methods"] == "GET"
    assert response.headers["access-control-allow-headers"] == "Content-Type"
    assert response.headers["cache-control"] == "public, max-age=3600"
    assert response.text == catalog.model_dump_json(by_alias=True, exclude_none=True)


async def test_mount_ai_catalog_on_existing_app() -> None:
    app = Starlette()
    mount_ai_catalog(app, AICatalog(entries=[]))
    response = await _get(app, "/.well-known/ai-catalog.json")
    assert response.status_code == 200
    assert AICatalog.model_validate(response.json()) == AICatalog(entries=[])


async def test_mount_ai_catalog_custom_path() -> None:
    app = Starlette()
    mount_ai_catalog(app, AICatalog(entries=[]), path="/.well-known/mcp/catalog.json")
    response = await _get(app, "/.well-known/mcp/catalog.json")
    assert response.status_code == 200
