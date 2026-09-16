"""Tests for client-side AI Catalog ingestion."""

import functools

import httpx2
import pytest
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

import mcp.client.experimental.ai_catalog as client_module
from mcp.client.experimental.ai_catalog import fetch_ai_catalog, well_known_ai_catalog_url
from mcp.server.experimental.ai_catalog import ai_catalog_route
from mcp.shared.experimental.ai_catalog import AICatalog

pytestmark = pytest.mark.anyio

CATALOG = AICatalog(spec_version="1.0", entries=[])


def test_well_known_ai_catalog_url_from_origin() -> None:
    assert well_known_ai_catalog_url("https://example.com") == "https://example.com/.well-known/ai-catalog.json"


def test_well_known_ai_catalog_url_from_endpoint_url() -> None:
    assert well_known_ai_catalog_url("https://example.com:8443/mcp?x=1") == (
        "https://example.com:8443/.well-known/ai-catalog.json"
    )


def test_well_known_ai_catalog_url_rejects_relative() -> None:
    with pytest.raises(ValueError) as excinfo:
        well_known_ai_catalog_url("example.com/mcp")
    assert str(excinfo.value) == "Expected an absolute http(s) URL, got 'example.com/mcp'"


def test_well_known_ai_catalog_url_rejects_non_http_scheme() -> None:
    with pytest.raises(ValueError) as excinfo:
        well_known_ai_catalog_url("ftp://example.com")
    assert str(excinfo.value) == "Expected an absolute http(s) URL, got 'ftp://example.com'"


async def test_fetch_with_provided_client() -> None:
    app = Starlette(routes=[ai_catalog_route(CATALOG)])
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport) as client:
        catalog = await fetch_ai_catalog("https://example.com/.well-known/ai-catalog.json", http_client=client)
    assert catalog == CATALOG


async def test_fetch_with_default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cover the branch that creates its own client, without touching the
    # network: bind the module's client factory to an in-memory ASGI transport.
    app = Starlette(routes=[ai_catalog_route(CATALOG)])
    transport = httpx2.ASGITransport(app=app)
    monkeypatch.setattr(
        client_module,
        "create_mcp_http_client",
        functools.partial(httpx2.AsyncClient, transport=transport, follow_redirects=True),
    )
    catalog = await fetch_ai_catalog("https://example.com/.well-known/ai-catalog.json")
    assert catalog == CATALOG


async def test_fetch_invalid_catalog_raises_validation_error() -> None:
    async def bad(_request: object) -> JSONResponse:
        return JSONResponse({"specVersion": "1.0"})  # entries missing

    app = Starlette(routes=[Route("/.well-known/ai-catalog.json", bad, methods=["GET"])])
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport) as client:
        with pytest.raises(ValidationError):
            await fetch_ai_catalog("https://example.com/.well-known/ai-catalog.json", http_client=client)


async def test_fetch_raises_for_http_error() -> None:
    app = Starlette(routes=[])  # nothing at the well-known path -> 404
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx2.HTTPStatusError):
            await fetch_ai_catalog("https://example.com/.well-known/ai-catalog.json", http_client=client)
