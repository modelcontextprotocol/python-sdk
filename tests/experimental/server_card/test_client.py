"""Tests for client-side Server Card ingestion."""

from __future__ import annotations

import functools
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

import mcp.client.experimental.server_card as client_module
from mcp.client.experimental.server_card import fetch_server_card, load_server_card, well_known_url
from mcp.server.experimental.server_card import server_card_route
from mcp.shared.experimental.server_card import ServerCard

pytestmark = pytest.mark.anyio

CARD = ServerCard(name="example/dice", version="1.0.0", description="Rolls dice.")


def test_well_known_url_from_origin() -> None:
    assert well_known_url("https://example.com") == "https://example.com/.well-known/mcp/server-card"


def test_well_known_url_from_endpoint_url() -> None:
    assert well_known_url("https://example.com:8443/mcp?x=1") == (
        "https://example.com:8443/.well-known/mcp/server-card"
    )


def test_well_known_url_custom_path() -> None:
    assert well_known_url("https://example.com", well_known_path="/.well-known/mcp-server-card") == (
        "https://example.com/.well-known/mcp-server-card"
    )


def test_well_known_url_rejects_relative() -> None:
    with pytest.raises(ValueError, match="absolute"):
        well_known_url("example.com/mcp")


async def test_fetch_with_provided_client() -> None:
    app = Starlette(routes=[server_card_route(CARD)])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport) as client:
        card = await fetch_server_card("https://example.com", httpx_client=client)
    assert card == CARD


async def test_fetch_with_default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cover the branch that creates its own client, without touching the network:
    # patch httpx.AsyncClient to one bound to an in-memory ASGI transport.
    app = Starlette(routes=[server_card_route(CARD)])
    transport = httpx.ASGITransport(app=app)
    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        functools.partial(httpx.AsyncClient, transport=transport),
    )
    card = await fetch_server_card("https://example.com")
    assert card == CARD


async def test_fetch_invalid_card_raises_validation_error() -> None:
    async def bad(_request: object) -> JSONResponse:
        return JSONResponse({"name": "missing-required-fields"})

    app = Starlette(routes=[Route("/.well-known/mcp/server-card", bad, methods=["GET"])])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValidationError):
            await fetch_server_card("https://example.com", httpx_client=client)


async def test_fetch_raises_for_http_error() -> None:
    app = Starlette(routes=[])  # nothing at the well-known path -> 404
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_server_card("https://example.com", httpx_client=client)


def test_load_server_card_from_file(tmp_path: Path) -> None:
    path = tmp_path / "server-card.json"
    path.write_text(json.dumps(CARD.model_dump(mode="json", by_alias=True, exclude_none=True)), encoding="utf-8")
    assert load_server_card(path) == CARD
