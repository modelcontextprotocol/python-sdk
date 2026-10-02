"""Tests for client-side Server Card ingestion and discovery."""

import functools
import json
from pathlib import Path

import httpx2
import pytest
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

import mcp.client.experimental.server_card as client_module
from mcp.client.experimental.server_card import discover_server_cards, fetch_server_card, load_server_card
from mcp.server.experimental.ai_catalog import ai_catalog_route, server_card_entry
from mcp.server.experimental.server_card import server_card_route
from mcp.shared.experimental.ai_catalog import AICatalog, CatalogEntry
from mcp.shared.experimental.server_card import ServerCard

pytestmark = pytest.mark.anyio

CARD = ServerCard(name="example/dice", version="1.0.0", description="Rolls dice.")
CARD_PATH = "/server-card.json"
CARD_URL = f"https://example.com{CARD_PATH}"


def make_discovery_app(*entries: CatalogEntry) -> Starlette:
    """An app serving an AI Catalog with ``entries`` plus the card itself."""
    catalog = AICatalog(
        spec_version="1.0",
        entries=list(entries) if entries else [server_card_entry(CARD, CARD_URL)],
    )
    routes = [server_card_route(CARD, path=CARD_PATH)]
    routes.append(ai_catalog_route(catalog))
    return Starlette(routes=routes)


async def test_fetch_server_card_from_url() -> None:
    transport = httpx2.ASGITransport(app=make_discovery_app())
    async with httpx2.AsyncClient(transport=transport) as client:
        card = await fetch_server_card(CARD_URL, http_client=client)
    assert card == CARD


async def test_fetch_server_card_with_default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cover the branch that creates its own client, without touching the
    # network: bind the module's client factory to an in-memory ASGI transport.
    transport = httpx2.ASGITransport(app=make_discovery_app())
    monkeypatch.setattr(
        client_module,
        "create_mcp_http_client",
        functools.partial(httpx2.AsyncClient, transport=transport, follow_redirects=True),
    )
    assert await fetch_server_card(CARD_URL) == CARD


async def test_fetch_invalid_card_raises_validation_error() -> None:
    async def bad(_request: object) -> JSONResponse:
        return JSONResponse({"name": "missing-required-fields"})

    app = Starlette(routes=[Route(CARD_PATH, bad, methods=["GET"])])
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport) as client:
        with pytest.raises(ValidationError):
            await fetch_server_card(CARD_URL, http_client=client)


async def test_fetch_raises_for_http_error() -> None:
    app = Starlette(routes=[])  # nothing at the card URL -> 404
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx2.HTTPStatusError):
            await fetch_server_card(CARD_URL, http_client=client)


async def test_discover_server_cards_via_well_known_catalog() -> None:
    transport = httpx2.ASGITransport(app=make_discovery_app())
    async with httpx2.AsyncClient(transport=transport) as client:
        cards = await discover_server_cards("https://example.com", http_client=client)
    assert cards == [CARD]


async def test_discover_server_cards_with_default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cover the branch that creates its own client, without touching the
    # network: bind the module's client factory to an in-memory ASGI transport.
    transport = httpx2.ASGITransport(app=make_discovery_app())
    monkeypatch.setattr(
        client_module,
        "create_mcp_http_client",
        functools.partial(httpx2.AsyncClient, transport=transport, follow_redirects=True),
    )
    assert await discover_server_cards("https://example.com") == [CARD]


async def test_discover_server_cards_resolves_relative_entry_url() -> None:
    entry = server_card_entry(CARD, CARD_PATH)  # relative to the catalog location
    transport = httpx2.ASGITransport(app=make_discovery_app(entry))
    async with httpx2.AsyncClient(transport=transport) as client:
        cards = await discover_server_cards("https://example.com/mcp", http_client=client)
    assert cards == [CARD]


async def test_discover_server_cards_reads_inline_data_entries() -> None:
    entry = CatalogEntry(
        identifier="urn:air:example:mcp:dice",
        media_type="application/mcp-server-card+json",
        data=CARD.model_dump(mode="json", by_alias=True, exclude_none=True),
    )
    transport = httpx2.ASGITransport(app=make_discovery_app(entry))
    async with httpx2.AsyncClient(transport=transport) as client:
        cards = await discover_server_cards("https://example.com", http_client=client)
    assert cards == [CARD]


async def test_discover_server_cards_ignores_non_card_entries() -> None:
    """Catalog entries that are not Server Cards are skipped."""
    other = CatalogEntry(
        identifier="urn:air:example.com:agent",
        media_type="application/a2a-agent-card+json",
        url="https://example.com/agent.json",
    )
    app = make_discovery_app(server_card_entry(CARD, CARD_URL), other)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport) as client:
        cards = await discover_server_cards("https://example.com", http_client=client)
    assert cards == [CARD]


async def test_discover_server_cards_rejects_non_http_card_url() -> None:
    """A hostile catalog must not steer the client to non-http(s) schemes."""
    entry = server_card_entry(CARD, CARD_URL).model_copy(update={"url": "file:///etc/passwd"})
    transport = httpx2.ASGITransport(app=make_discovery_app(entry))
    async with httpx2.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError) as excinfo:
            await discover_server_cards("https://example.com", http_client=client)
    assert str(excinfo.value) == (
        "catalog entry 'urn:air:example:mcp:dice' has a non-http(s) card URL: 'file:///etc/passwd'"
    )


async def test_discover_server_cards_raises_when_no_catalog_exists() -> None:
    app = Starlette(routes=[])
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx2.HTTPStatusError):
            await discover_server_cards("https://example.com", http_client=client)


async def test_discover_server_cards_propagates_catalog_http_errors() -> None:
    async def error(_request: object) -> Response:
        return Response(status_code=500)

    app = Starlette(routes=[Route("/.well-known/ai-catalog.json", error, methods=["GET"])])
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx2.HTTPStatusError) as excinfo:
            await discover_server_cards("https://example.com", http_client=client)
    assert excinfo.value.response.status_code == 500


def test_load_server_card_from_file(tmp_path: Path) -> None:
    path = tmp_path / "server-card.json"
    path.write_text(json.dumps(CARD.model_dump(mode="json", by_alias=True, exclude_none=True)), encoding="utf-8")
    assert load_server_card(path) == CARD
