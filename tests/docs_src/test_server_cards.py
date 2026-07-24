"""`docs/advanced/server-cards.md`: every claim the page makes, proved against the real SDK."""

import ipaddress
from pathlib import Path

import httpx2
import pytest

from docs_src.server_cards import tutorial001, tutorial002, tutorial003, tutorial004
from mcp import Client
from mcp.client.experimental import _discovery_http
from mcp.client.experimental.server_card import discover_server_cards, load_server_card, reconcile_server_card
from mcp.shared.experimental.server_card import Input, Remote, resolve_remote

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "d", "version": "1"}},
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin DNS to a public address so the default discovery policy runs offline.

    The SSRF guard resolves every hostname before the request, and the page's
    example domains do not resolve in CI.
    """

    async def resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(_discovery_http, "_host_addresses", resolve)


async def test_mount_discovery_serves_both_endpoints_with_the_spec_headers() -> None:
    """tutorial001: the two GET endpoints exist beside the live transport, with the
    page's promised Content-Type, CORS, Cache-Control and ETag/304 behavior."""
    transport = httpx2.ASGITransport(app=tutorial001.app)
    async with tutorial001.mcp.session_manager.run():
        async with httpx2.AsyncClient(transport=transport, base_url="http://localhost:8000") as http:
            initialize = await http.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
            card_response = await http.get("/mcp/server-card")
            catalog_response = await http.get("/.well-known/ai-catalog.json")
            revalidated = await http.get("/mcp/server-card", headers={"If-None-Match": card_response.headers["etag"]})
    assert initialize.status_code == 200
    assert card_response.headers["content-type"] == "application/mcp-server-card+json"
    assert card_response.headers["access-control-allow-origin"] == "*"
    assert card_response.headers["access-control-allow-methods"] == "GET"
    assert card_response.headers["access-control-allow-headers"] == "Content-Type"
    assert card_response.headers["cache-control"] == "public, max-age=3600"
    assert catalog_response.headers["content-type"] == "application/ai-catalog+json"
    assert (revalidated.status_code, revalidated.content) == (304, b"")


async def test_build_server_card_keeps_the_card_consistent_with_server_info() -> None:
    """tutorial001 + the page's derivation claim: the card carries the server's version,
    description and websiteUrl, so `reconcile_server_card` finds no drift after connect."""
    assert tutorial001.card.version == "1.4.0"
    assert tutorial001.card.description == "Hourly forecasts."
    assert tutorial001.card.website_url == "https://example.com"
    async with Client(tutorial001.mcp) as client:
        assert reconcile_server_card(tutorial001.card, client.server_info) == []


async def test_the_discovery_probe_finds_the_served_card(public_dns: None) -> None:
    """tutorial002: `discover_server_cards` on any page of the origin finds the card
    tutorial001 mounted, and the listing exposes the consent-UI domains and the endpoint
    dedup key. The tutorial's `main()` itself needs a live network, so the flow is
    proved here against the in-memory app."""
    http_client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=tutorial001.app), base_url="https://mcp.example.com"
    )
    async with http_client:
        result = await discover_server_cards("https://mcp.example.com/docs", http_client=http_client)
    assert result.failures == []
    (listing,) = result.listings
    assert listing.entry.identifier == "urn:air:mcp.example.com:mcp:weather"
    assert (listing.listing_domain, listing.hosting_domain) == ("mcp.example.com", "mcp.example.com")
    assert listing.card.endpoint_urls() == frozenset({"https://mcp.example.com/mcp"})
    assert listing.card == tutorial001.card


def test_resolve_remote_names_every_missing_required_input() -> None:
    """tutorial002's comment: `resolve_remote` raises a ValueError naming the missing
    required inputs so a host can prompt for all of them at once."""
    remote = Remote(
        type="streamable-http",
        url="https://{tenant}.example.com/mcp",
        variables={"tenant": Input(is_required=True)},
    )
    assert remote.required_variables == frozenset({"tenant"})
    with pytest.raises(ValueError, match="tenant"):
        resolve_remote(remote)
    assert resolve_remote(remote, {"tenant": "acme"}).url == "https://acme.example.com/mcp"


async def test_the_revalidation_recipe_costs_a_304_when_unchanged() -> None:
    """tutorial003: the first `refresh` parses and stores the card, the second sends the
    stored ETag and reuses the cache on the 304."""
    store = tutorial003.CardStore()
    transport = httpx2.ASGITransport(app=tutorial001.app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://mcp.example.com") as http:
        first = await tutorial003.refresh(store, http, "https://mcp.example.com/mcp/server-card")
        second = await tutorial003.refresh(store, http, "https://mcp.example.com/mcp/server-card")
    assert first == tutorial001.card
    assert second is first
    assert store.etags["https://mcp.example.com/mcp/server-card"].startswith('"')


def test_static_publishing_writes_a_loadable_card(tmp_path: Path) -> None:
    """tutorial004: the written file is a valid card document that loads back."""
    target = tmp_path / "server-card.json"
    tutorial004.publish(target)
    assert load_server_card(target) == tutorial004.card


def test_the_connect_tutorial_exposes_its_client_program() -> None:
    """tutorial002's `main()` needs a live network, so its coverage here is the import
    plus the in-memory proof of the same flow above."""
    assert callable(tutorial002.main)
