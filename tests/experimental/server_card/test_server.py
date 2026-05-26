"""Tests for server-side Server Card generation and serving."""

from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette

from mcp.client.experimental.server_card import fetch_server_card
from mcp.server.experimental.server_card import (
    build_server_card,
    mount_server_card,
    server_card_route,
)
from mcp.server.lowlevel import Server
from mcp.shared.experimental.server_card import Remote, Repository, ServerCard

pytestmark = pytest.mark.anyio


def make_server() -> Server:
    return Server(
        "dice-roller",
        version="1.0.0",
        title="Dice Roller",
        description="Rolls dice for tabletop games.",
        website_url="https://example.com/dice",
    )


def test_build_server_card_from_server_identity() -> None:
    card = build_server_card(
        make_server(),
        name="io.modelcontextprotocol.examples/dice-roller",
        remotes=[Remote(type="streamable-http", url="https://dice.example.com/mcp")],
        repository=Repository(url="https://github.com/example/dice", source="github"),
        meta={"com.example/x": 1},
    )
    assert card.name == "io.modelcontextprotocol.examples/dice-roller"
    assert card.version == "1.0.0"
    assert card.title == "Dice Roller"
    assert card.description == "Rolls dice for tabletop games."
    assert card.website_url == "https://example.com/dice"
    assert card.remotes is not None and card.remotes[0].url == "https://dice.example.com/mcp"
    assert card.meta == {"com.example/x": 1}


def test_build_server_card_requires_version() -> None:
    server = Server("no-version", description="desc")  # version defaults to None
    with pytest.raises(ValueError, match="version"):
        build_server_card(server, name="example/no-version")


def test_build_server_card_requires_description() -> None:
    server = Server("no-desc", version="1.0.0")  # description defaults to None
    with pytest.raises(ValueError, match="description"):
        build_server_card(server, name="example/no-desc")


async def _get(app: Starlette, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://dice.example.com") as client:
        return await client.get(path)


async def test_server_card_route_serves_json() -> None:
    card = build_server_card(make_server(), name="example/dice")
    app = Starlette(routes=[server_card_route(card)])
    response = await _get(app, "/.well-known/mcp/server-card")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert ServerCard.model_validate(response.json()) == card


async def test_mount_server_card_on_existing_app_and_client_fetch() -> None:
    card = build_server_card(
        make_server(),
        name="example/dice",
        remotes=[Remote(type="streamable-http", url="https://dice.example.com/mcp")],
    )
    app = Starlette()
    mount_server_card(app, card)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport) as client:
        fetched = await fetch_server_card("https://dice.example.com", httpx_client=client)
    assert fetched == card


async def test_mount_server_card_custom_path() -> None:
    card = build_server_card(make_server(), name="example/dice")
    app = Starlette()
    mount_server_card(app, card, path="/custom/card.json")
    response = await _get(app, "/custom/card.json")
    assert response.status_code == 200
