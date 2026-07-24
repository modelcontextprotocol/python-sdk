"""`mcp.client.experimental.server_card`: hardened fetch, discovery, revalidation, reconcile."""

import ipaddress
import json
import socket
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import anyio
import httpx2
import pytest
from inline_snapshot import snapshot
from mcp_types import Implementation
from pydantic import ValidationError
from starlette.applications import Starlette

from mcp import Client
from mcp.client.experimental import _discovery_http
from mcp.client.experimental.server_card import (
    CardListing,
    DiscoveryError,
    DiscoveryErrorReason,
    DiscoveryPolicy,
    DiscoveryResult,
    create_ai_catalog_request,
    create_server_card_request,
    discover_server_cards,
    fetch_ai_catalog,
    fetch_server_card,
    load_server_card,
    parse_ai_catalog_response,
    parse_server_card_response,
    reconcile_server_card,
    server_card_url,
    well_known_ai_catalog_url,
)
from mcp.server import MCPServer
from mcp.server.experimental.server_card import build_server_card, mount_discovery
from mcp.shared.experimental.ai_catalog import AICatalog, CatalogEntry
from mcp.shared.experimental.server_card import Remote, ServerCard

pytestmark = pytest.mark.anyio

CARD_MEDIA_TYPE = "application/mcp-server-card+json"
CATALOG_MEDIA_TYPE = "application/ai-catalog+json"


def _card(name: str = "com.example/weather") -> ServerCard:
    return ServerCard(
        name=name,
        version="1.4.0",
        description="Hourly forecasts.",
        remotes=[Remote(type="streamable-http", url="https://mcp.example.com/mcp")],
    )


def _card_bytes(name: str = "com.example/weather") -> bytes:
    return _card(name).model_dump_json(by_alias=True, exclude_none=True).encode()


def _catalog_bytes(entries: list[dict[str, Any]]) -> bytes:
    return json.dumps({"specVersion": "1.0", "entries": entries}).encode()


def _mock_client(
    handler: Callable[[httpx2.Request], httpx2.Response]
    | Callable[[httpx2.Request], Coroutine[None, None, httpx2.Response]],
) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def _refuse_all(request: httpx2.Request) -> httpx2.Response:
    raise NotImplementedError


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin DNS so default-policy tests stay deterministic and offline.

    The address guard resolves every hostname before the request. Stubbing the
    private resolver to a public address is the only way to exercise the
    default (hardened) policy against an in-memory transport without real DNS.
    """

    async def resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        try:
            return [ipaddress.ip_address(host)]  # IP literals keep their real meaning
        except ValueError:
            return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(_discovery_http, "_host_addresses", resolve)


# -- fetch happy paths --------------------------------------------------------------------


async def test_fetch_server_card_sends_the_accept_header_and_parses_the_card(public_dns: None) -> None:
    """Spec-mandated: the client sends `Accept: application/mcp-server-card+json` and
    parses the canonical media type."""
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, content=_card_bytes(), headers={"Content-Type": CARD_MEDIA_TYPE})

    async with _mock_client(handler) as client:
        card = await fetch_server_card("https://example.com/mcp/server-card", http_client=client)
    assert card == _card()
    assert seen[0].headers["accept"] == "application/mcp-server-card+json, application/json;q=0.5"


async def test_fetch_accepts_media_type_parameters_and_plain_json(public_dns: None) -> None:
    """SDK-defined lenience: `; charset=` parameters are ignored and plain
    `application/json` passes, because static hosts and CDNs commonly serve it."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("server-card"):
            return httpx2.Response(
                200, content=_card_bytes(), headers={"Content-Type": f"{CARD_MEDIA_TYPE}; charset=utf-8"}
            )
        return httpx2.Response(200, content=_catalog_bytes([]), headers={"Content-Type": "application/json"})

    async with _mock_client(handler) as client:
        card = await fetch_server_card("https://example.com/mcp/server-card", http_client=client)
        catalog = await fetch_ai_catalog("https://example.com/.well-known/ai-catalog.json", http_client=client)
    assert card == _card()
    assert catalog == AICatalog(spec_version="1.0", entries=[])


async def test_fetch_rejects_a_malformed_card_document(public_dns: None) -> None:
    """SDK-defined: document shape failures stay `pydantic.ValidationError`, distinct
    from transport and policy failures."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b'{"name": "no-namespace"}', headers={"Content-Type": CARD_MEDIA_TYPE})

    async with _mock_client(handler) as client:
        with pytest.raises(ValidationError):
            await fetch_server_card("https://example.com/mcp/server-card", http_client=client)


# -- policy failures ------------------------------------------------------------------------


async def test_non_2xx_status_raises_with_reason_status(public_dns: None) -> None:
    """SDK-defined: a non-2xx answer becomes a `DiscoveryError` naming the URL, with the
    `httpx2.HTTPStatusError` chained as the cause."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404)

    async with _mock_client(handler) as client:
        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_server_card("https://example.com/mcp/server-card", http_client=client)
    assert exc_info.value.reason == "status"
    assert exc_info.value.url == "https://example.com/mcp/server-card"
    assert isinstance(exc_info.value.__cause__, httpx2.HTTPStatusError)


async def test_wrong_media_type_raises_with_reason_media_type(public_dns: None) -> None:
    """Spec-mandated: hosts must respect the card media type, so `text/html` (a typical
    captive error page) is rejected."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"<html></html>", headers={"Content-Type": "text/html"})

    async with _mock_client(handler) as client:
        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_server_card("https://example.com/mcp/server-card", http_client=client)
    assert exc_info.value.reason == "media_type"


async def test_a_body_over_the_size_cap_raises_mid_stream(public_dns: None) -> None:
    """SDK-defined (best practices): response size is capped and enforced while
    streaming, so an oversized document fails without being buffered whole."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"x" * 64, headers={"Content-Type": CARD_MEDIA_TYPE})

    async with _mock_client(handler) as client:
        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_server_card(
                "https://example.com/mcp/server-card",
                http_client=client,
                policy=DiscoveryPolicy(max_response_bytes=16),
            )
    assert exc_info.value.reason == "response_too_large"


async def test_redirects_are_followed_within_the_cap(public_dns: None) -> None:
    """SDK-defined (best practices): redirects are walked manually, resolving relative
    `Location` values, and the final document parses normally."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/old":
            return httpx2.Response(301, headers={"Location": "/newer"})
        if request.url.path == "/newer":
            return httpx2.Response(302, headers={"Location": "https://example.com/final"})
        assert request.url.path == "/final"
        return httpx2.Response(200, content=_card_bytes(), headers={"Content-Type": CARD_MEDIA_TYPE})

    async with _mock_client(handler) as client:
        card = await fetch_server_card("https://example.com/old", http_client=client)
    assert card == _card()


async def test_redirects_past_the_cap_raise(public_dns: None) -> None:
    """SDK-defined (best practices): the redirect budget is bounded."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(302, headers={"Location": "https://example.com/loop"})

    async with _mock_client(handler) as client:
        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_server_card(
                "https://example.com/loop", http_client=client, policy=DiscoveryPolicy(max_redirects=1)
            )
    assert exc_info.value.reason == "too_many_redirects"


async def test_a_redirect_without_location_raises(public_dns: None) -> None:
    """SDK-defined: a 3xx with no `Location` header cannot be followed."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(302)

    async with _mock_client(handler) as client:
        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_server_card("https://example.com/mcp/server-card", http_client=client)
    assert exc_info.value.reason == "status"


async def test_each_redirect_hop_is_revalidated(public_dns: None) -> None:
    """SDK-defined (best practices): a public origin redirecting into a private range is
    caught on the hop, not trusted because the first URL was fine."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(302, headers={"Location": "https://10.0.0.1/internal"})

    async with _mock_client(handler) as client:
        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_server_card("https://example.com/mcp/server-card", http_client=client)
    assert exc_info.value.reason == "blocked_address"
    assert exc_info.value.url == "https://10.0.0.1/internal"


@pytest.mark.parametrize(
    "url",
    [
        "https://10.0.0.1/mcp/server-card",
        "https://172.16.0.5/mcp/server-card",
        "https://192.168.1.1/mcp/server-card",
        "https://169.254.169.254/latest/meta-data",
        "https://100.64.0.1/mcp/server-card",
        "https://224.0.0.1/mcp/server-card",
        "https://240.0.0.1/mcp/server-card",
        "https://0.0.0.0/mcp/server-card",
        "https://127.0.0.1/mcp/server-card",
        "https://[::1]/mcp/server-card",
        "https://[fc00::1]/mcp/server-card",
        "https://[fe80::1]/mcp/server-card",
        "https://[::ffff:10.0.0.1]/mcp/server-card",
        "https://[::ffff:100.64.0.1]/mcp/server-card",
    ],
)
async def test_ip_literal_targets_off_the_public_internet_are_blocked(url: str) -> None:
    """SDK-defined (best practices): loopback, link-local (including the cloud metadata
    endpoint), private, CGNAT, multicast, reserved, unspecified and IPv4-mapped IPv6
    literals never get a request. The handler proves it by refusing to answer."""
    async with _mock_client(_refuse_all) as client:
        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_server_card(url, http_client=client)
    assert exc_info.value.reason == "blocked_address"


async def test_a_hostname_resolving_to_a_private_address_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK-defined (best practices): the guard re-checks after DNS resolution, so a
    public-looking hostname pointing into a private range is rejected."""

    async def resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        return [ipaddress.ip_address("10.9.8.7")]

    monkeypatch.setattr(_discovery_http, "_host_addresses", resolve)
    async with _mock_client(_refuse_all) as client:
        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_server_card("https://internal.example.com/mcp/server-card", http_client=client)
    assert exc_info.value.reason == "blocked_address"


async def test_localhost_is_blocked_under_the_default_policy() -> None:
    """SDK-defined: `https://localhost` resolves (via the real resolver) to loopback and
    is blocked. Local development opts in with `allow_private_addresses=True`."""
    async with _mock_client(_refuse_all) as client:
        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_server_card("https://localhost/mcp/server-card", http_client=client)
    assert exc_info.value.reason == "blocked_address"


@pytest.mark.parametrize("url", ["http://example.com/mcp/server-card", "http://127.0.0.1/mcp/server-card"])
async def test_plain_http_raises_insecure_transport_under_the_default_policy(url: str) -> None:
    """Spec-mandated: HTTPS is a MUST in production. Under the hardened policy even a
    loopback http target is refused up front (its address would be blocked anyway);
    local development opts in with `allow_private_addresses=True`."""
    async with _mock_client(_refuse_all) as client:
        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_server_card(url, http_client=client)
    assert exc_info.value.reason == "insecure_transport"


async def test_a_url_carrying_userinfo_is_rejected_before_any_request() -> None:
    """SDK-defined hardening: `https://github.com@evil.example/...` reads as a trusted
    brand but names `evil.example`. Discovery never sends credentials, so userinfo URLs
    never get a request. The handler proves it by refusing to answer."""
    async with _mock_client(_refuse_all) as client:
        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_server_card("https://github.com@evil.example/mcp/server-card", http_client=client)
    assert exc_info.value.reason == "insecure_transport"


@pytest.mark.parametrize("url", ["ftp://example.com/card", "/mcp/server-card"])
async def test_non_http_and_relative_urls_raise_insecure_transport(url: str) -> None:
    """SDK-defined: discovery only ever speaks absolute http(s)."""
    async with _mock_client(_refuse_all) as client:
        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_server_card(url, http_client=client)
    assert exc_info.value.reason == "insecure_transport"


async def test_allow_private_addresses_permits_local_development() -> None:
    """SDK-defined: the local-dev policy admits plain http to localhost and private
    targets, skipping the scheme and address guards."""
    policy = DiscoveryPolicy(allow_private_addresses=True)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=_card_bytes(), headers={"Content-Type": CARD_MEDIA_TYPE})

    async with _mock_client(handler) as client:
        via_localhost = await fetch_server_card(
            "http://localhost:8000/mcp/server-card", http_client=client, policy=policy
        )
        via_private_ip = await fetch_server_card("https://10.0.0.1/mcp/server-card", http_client=client, policy=policy)
    assert via_localhost == _card()
    assert via_private_ip == _card()


async def test_the_default_client_path_applies_the_same_guards() -> None:
    """SDK-defined: with no `http_client`, a fresh credential-free client is created and
    the URL is still admitted first. A blocked target fails before any request."""
    with pytest.raises(DiscoveryError) as exc_info:
        await fetch_server_card("https://10.0.0.1/mcp/server-card")
    assert exc_info.value.reason == "blocked_address"


# -- discover_server_cards -------------------------------------------------------------------


async def test_discover_probes_the_well_known_path_of_the_origin(public_dns: None) -> None:
    """Spec-mandated: any user-entered URL probes exactly its origin's
    `/.well-known/ai-catalog.json`, then follows card entries by URL."""
    seen_paths: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/.well-known/ai-catalog.json":
            entry = {
                "identifier": "urn:air:example.com:mcp:weather",
                "type": CARD_MEDIA_TYPE,
                "url": "https://example.com/mcp/server-card",
            }
            return httpx2.Response(200, content=_catalog_bytes([entry]), headers={"Content-Type": CATALOG_MEDIA_TYPE})
        return httpx2.Response(200, content=_card_bytes(), headers={"Content-Type": CARD_MEDIA_TYPE})

    async with _mock_client(handler) as client:
        result = await discover_server_cards("https://example.com/docs/page?q=1", http_client=client)
    assert seen_paths[0] == "/.well-known/ai-catalog.json"
    assert result.failures == []
    (listing,) = result.listings
    assert listing.card == _card()
    assert listing.catalog_url == "https://example.com/.well-known/ai-catalog.json"
    assert listing.card_url == "https://example.com/mcp/server-card"
    assert (listing.listing_domain, listing.hosting_domain) == ("example.com", "example.com")


async def test_discover_reads_inline_data_entries_without_a_fetch(public_dns: None) -> None:
    """Spec-mandated: an entry may inline the card as `data`. No card URL exists, so the
    hosting domain is None."""
    inline = {
        "identifier": "urn:air:example.com:mcp:weather",
        "type": CARD_MEDIA_TYPE,
        "data": json.loads(_card_bytes()),
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=_catalog_bytes([inline]), headers={"Content-Type": CATALOG_MEDIA_TYPE})

    async with _mock_client(handler) as client:
        result = await discover_server_cards("https://example.com", http_client=client)
    (listing,) = result.listings
    assert listing.card == _card()
    assert listing.card_url is None
    assert listing.hosting_domain is None


async def test_discover_follows_nested_catalogs_by_url_and_inline(public_dns: None) -> None:
    """Spec-mandated: catalog entries may be catalogs themselves. Listings keep the
    nested catalog's URL as their listing source; an inline nested catalog keeps the
    document it was embedded in."""
    inline_card = {
        "identifier": "urn:air:example.com:mcp:inline",
        "type": CARD_MEDIA_TYPE,
        "data": json.loads(_card_bytes("com.example/inline")),
    }
    nested_by_url = {
        "identifier": "urn:air:example.com:catalog:more",
        "type": CATALOG_MEDIA_TYPE,
        "url": "https://example.com/more-catalog.json",
    }
    nested_inline = {
        "identifier": "urn:air:example.com:catalog:embedded",
        "type": CATALOG_MEDIA_TYPE,
        "data": json.loads(_catalog_bytes([inline_card])),
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/.well-known/ai-catalog.json":
            body = _catalog_bytes([nested_by_url, nested_inline])
        else:
            assert request.url.path == "/more-catalog.json"
            card_entry = {
                "identifier": "urn:air:example.com:mcp:weather",
                "type": CARD_MEDIA_TYPE,
                "data": json.loads(_card_bytes()),
            }
            body = _catalog_bytes([card_entry])
        return httpx2.Response(200, content=body, headers={"Content-Type": CATALOG_MEDIA_TYPE})

    async with _mock_client(handler) as client:
        result = await discover_server_cards("https://example.com", http_client=client)
    assert result.failures == []
    assert [listing.catalog_url for listing in result.listings] == [
        "https://example.com/more-catalog.json",
        "https://example.com/.well-known/ai-catalog.json",
    ]


async def test_discover_records_a_depth_cap_failure_instead_of_recursing(public_dns: None) -> None:
    """SDK-defined (AI Catalog spec cap): nesting past `max_catalog_depth` becomes one
    failure with reason `catalog_depth`, never an unbounded walk."""
    nested = {
        "identifier": "urn:air:example.com:catalog:deep",
        "type": CATALOG_MEDIA_TYPE,
        "url": "https://example.com/deep.json",
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=_catalog_bytes([nested]), headers={"Content-Type": CATALOG_MEDIA_TYPE})

    async with _mock_client(handler) as client:
        result = await discover_server_cards(
            "https://example.com", http_client=client, policy=DiscoveryPolicy(max_catalog_depth=1)
        )
    assert result.listings == []
    (failure,) = result.failures
    assert isinstance(failure.error, DiscoveryError)
    assert failure.error.reason == "catalog_depth"
    assert failure.entry_identifier == "urn:air:example.com:catalog:deep"


async def test_discover_ignores_entries_of_other_artifact_types(public_dns: None) -> None:
    """Spec-mandated: catalogs legitimately advertise other artifacts. They are neither
    listings nor failures."""
    other = {
        "identifier": "urn:air:example.com:agent:helper",
        "type": "application/agent-card+json",
        "url": "https://example.com/agent.json",
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=_catalog_bytes([other]), headers={"Content-Type": CATALOG_MEDIA_TYPE})

    async with _mock_client(handler) as client:
        result = await discover_server_cards("https://example.com", http_client=client)
    assert (result.listings, result.failures) == ([], [])


async def test_discover_collects_per_entry_failures_and_keeps_good_listings(public_dns: None) -> None:
    """SDK-defined (best practices): one hostile or broken entry never kills the probe.
    Failures are collected with their entry identifiers while good entries still list."""
    entries = [
        {"identifier": "urn:air:example.com:mcp:good", "type": CARD_MEDIA_TYPE, "data": json.loads(_card_bytes())},
        {"identifier": "urn:air:example.com:mcp:gone", "type": CARD_MEDIA_TYPE, "url": "https://example.com/gone"},
        {"identifier": "urn:air:example.com:mcp:bad", "type": CARD_MEDIA_TYPE, "data": {"name": "not-a-card"}},
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/.well-known/ai-catalog.json":
            return httpx2.Response(200, content=_catalog_bytes(entries), headers={"Content-Type": CATALOG_MEDIA_TYPE})
        return httpx2.Response(404)

    async with _mock_client(handler) as client:
        result = await discover_server_cards("https://example.com", http_client=client)
    assert [listing.entry.identifier for listing in result.listings] == ["urn:air:example.com:mcp:good"]
    assert [failure.entry_identifier for failure in result.failures] == [
        "urn:air:example.com:mcp:gone",
        "urn:air:example.com:mcp:bad",
    ]
    assert isinstance(result.failures[0].error, DiscoveryError)
    assert isinstance(result.failures[1].error, ValidationError)


async def test_discover_caps_the_entry_count_and_records_the_excess(public_dns: None) -> None:
    """SDK-defined (best practices): entry count is capped. The excess is recorded as
    one failure on the catalog itself, not silently dropped."""
    entries = [
        {"identifier": f"urn:air:example.com:mcp:c{i}", "type": CARD_MEDIA_TYPE, "data": json.loads(_card_bytes())}
        for i in range(3)
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=_catalog_bytes(entries), headers={"Content-Type": CATALOG_MEDIA_TYPE})

    async with _mock_client(handler) as client:
        result = await discover_server_cards(
            "https://example.com", http_client=client, policy=DiscoveryPolicy(max_catalog_entries=2)
        )
    assert [listing.entry.identifier for listing in result.listings] == [
        "urn:air:example.com:mcp:c0",
        "urn:air:example.com:mcp:c1",
    ]
    (failure,) = result.failures
    assert failure.entry_identifier is None
    assert isinstance(failure.error, DiscoveryError)
    assert failure.error.reason == "invalid_entry"


async def test_discover_keeps_other_listings_when_an_entry_host_does_not_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SDK-defined (best practices): the address guard resolves DNS itself, so an
    unresolvable entry host raises `socket.gaierror`, the most likely hostile or broken
    entry shape. It becomes a failure while the good entries still list."""

    async def resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        if host == "gone.invalid":
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(_discovery_http, "_host_addresses", resolve)
    entries = [
        {"identifier": "urn:air:example.com:mcp:good", "type": CARD_MEDIA_TYPE, "data": json.loads(_card_bytes())},
        {"identifier": "urn:air:example.com:mcp:gone", "type": CARD_MEDIA_TYPE, "url": "https://gone.invalid/card"},
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=_catalog_bytes(entries), headers={"Content-Type": CATALOG_MEDIA_TYPE})

    async with _mock_client(handler) as client:
        result = await discover_server_cards("https://example.com", http_client=client)
    assert [listing.entry.identifier for listing in result.listings] == ["urn:air:example.com:mcp:good"]
    (failure,) = result.failures
    assert failure.entry_identifier == "urn:air:example.com:mcp:gone"
    assert isinstance(failure.error, socket.gaierror)


async def test_discover_keeps_other_listings_when_an_entry_times_out(public_dns: None) -> None:
    """SDK-defined (best practices): a tar-pit entry hits the per-fetch deadline
    (`TimeoutError`) and becomes a failure while the good entries still list. The sleep
    is the thing under test here (the deadline is a time-based feature), and the probe
    runs in a child task because the deadline's cancellation stops coverage tracing in
    every frame still suspended on the awaited call."""
    entries = [
        {"identifier": "urn:air:example.com:mcp:good", "type": CARD_MEDIA_TYPE, "data": json.loads(_card_bytes())},
        {"identifier": "urn:air:example.com:mcp:slow", "type": CARD_MEDIA_TYPE, "url": "https://example.com/tar-pit"},
    ]

    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/.well-known/ai-catalog.json":
            return httpx2.Response(200, content=_catalog_bytes(entries), headers={"Content-Type": CATALOG_MEDIA_TYPE})
        await anyio.sleep(3600)  # cancelled by the per-fetch deadline
        raise NotImplementedError

    results: list[DiscoveryResult] = []

    async def probe() -> None:
        async with _mock_client(handler) as client:
            results.append(
                await discover_server_cards(
                    "https://example.com", http_client=client, policy=DiscoveryPolicy(timeout_seconds=0.05)
                )
            )

    with anyio.fail_after(5):
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(probe)
    (result,) = results
    assert [listing.entry.identifier for listing in result.listings] == ["urn:air:example.com:mcp:good"]
    (failure,) = result.failures
    assert failure.entry_identifier == "urn:air:example.com:mcp:slow"
    assert isinstance(failure.error, TimeoutError)


async def test_discover_never_refetches_an_already_visited_catalog(public_dns: None) -> None:
    """SDK-defined (best practices): a nested entry pointing back at an already-walked
    catalog URL (here the well-known catalog itself) is skipped, not refetched, so a
    self-referential catalog terminates after one fetch with no failure."""
    entries = [
        {
            "identifier": "urn:air:example.com:catalog:self",
            "type": CATALOG_MEDIA_TYPE,
            "url": "https://example.com/.well-known/ai-catalog.json",
        },
        {"identifier": "urn:air:example.com:mcp:good", "type": CARD_MEDIA_TYPE, "data": json.loads(_card_bytes())},
    ]
    seen_paths: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_paths.append(request.url.path)
        return httpx2.Response(200, content=_catalog_bytes(entries), headers={"Content-Type": CATALOG_MEDIA_TYPE})

    async with _mock_client(handler) as client:
        result = await discover_server_cards("https://example.com", http_client=client)
    assert seen_paths == ["/.well-known/ai-catalog.json"]
    assert [listing.entry.identifier for listing in result.listings] == ["urn:air:example.com:mcp:good"]
    assert result.failures == []


async def test_discover_stops_at_the_probe_budget_with_a_single_failure(public_dns: None) -> None:
    """SDK-defined (best practices): the per-catalog entry cap and the depth cap are
    multiplicative, so a hostile catalog tree could amplify one probe into
    `entries**depth` fetches. `max_probe_entries` bounds the aggregate walk: everything
    past the budget is dropped after one `probe_budget` failure, never one per entry."""

    def card_entry(number: int) -> dict[str, Any]:
        return {
            "identifier": f"urn:air:example.com:mcp:c{number}",
            "type": CARD_MEDIA_TYPE,
            "url": f"https://example.com/card/{number}",
        }

    def nested_entry(number: int) -> dict[str, Any]:
        return {
            "identifier": f"urn:air:example.com:catalog:n{number}",
            "type": CATALOG_MEDIA_TYPE,
            "url": f"https://example.com/nested/{number}",
        }

    seen_paths: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/.well-known/ai-catalog.json":
            body = _catalog_bytes([card_entry(1), card_entry(2), nested_entry(1), nested_entry(2)])
        elif request.url.path.startswith("/nested/"):
            body = _catalog_bytes([card_entry(3)])
        else:
            return httpx2.Response(200, content=_card_bytes(), headers={"Content-Type": CARD_MEDIA_TYPE})
        return httpx2.Response(200, content=body, headers={"Content-Type": CATALOG_MEDIA_TYPE})

    async with _mock_client(handler) as client:
        result = await discover_server_cards(
            "https://example.com", http_client=client, policy=DiscoveryPolicy(max_probe_entries=3)
        )
    # Budget of 3: card 1, card 2, then nested catalog 1. Its own card entry finds the
    # budget spent (one failure), and nested catalog 2 is dropped without another.
    assert seen_paths == ["/.well-known/ai-catalog.json", "/card/1", "/card/2", "/nested/1"]
    assert [listing.entry.identifier for listing in result.listings] == [
        "urn:air:example.com:mcp:c1",
        "urn:air:example.com:mcp:c2",
    ]
    (failure,) = result.failures
    assert failure.entry_identifier is None
    assert isinstance(failure.error, DiscoveryError)
    expected_reason: DiscoveryErrorReason = "probe_budget"
    assert failure.error.reason == expected_reason


def test_listing_domains_are_host_and_port_never_userinfo() -> None:
    """SDK-defined hardening: the consent-UI domain properties show host[:port] only, so
    a `user@host` URL in a hand-built listing cannot lead with a trusted brand; IPv6
    hosts keep their brackets and a URL with no host shows as empty."""

    def listing_for(url: str) -> CardListing:
        entry = CatalogEntry(identifier="urn:air:example.com:mcp:weather", type=CARD_MEDIA_TYPE, url=url)
        return CardListing(card=_card(), entry=entry, catalog_url=url, card_url=url)

    assert listing_for("https://github.com@evil.example/card").listing_domain == "evil.example"
    assert listing_for("https://user:pass@example.com:8443/card").hosting_domain == "example.com:8443"
    assert listing_for("https://[2001:db8::1]:8443/card").listing_domain == "[2001:db8::1]:8443"
    assert listing_for("https:///card").listing_domain == ""


async def test_discover_with_the_default_client_applies_the_same_guards() -> None:
    """SDK-defined: with no `http_client`, one fresh credential-free client serves the
    whole probe, and a blocked target still fails before any request."""
    with pytest.raises(DiscoveryError) as exc_info:
        await discover_server_cards("https://10.0.0.1/docs")
    assert exc_info.value.reason == "blocked_address"


async def test_discover_raises_when_the_catalog_itself_fails(public_dns: None) -> None:
    """SDK-defined: a probe that cannot read the top-level catalog found nothing usable,
    so that failure raises instead of returning an empty result."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404)

    async with _mock_client(handler) as client:
        with pytest.raises(DiscoveryError) as exc_info:
            await discover_server_cards("https://example.com", http_client=client)
    assert exc_info.value.reason == "status"


async def test_discover_rejects_a_non_http_input_url() -> None:
    """SDK-defined: only http(s) URLs have an origin to probe."""
    with pytest.raises(ValueError, match="absolute http"):
        await discover_server_cards("mailto:ops@example.com")


# -- end to end against the real server routes ------------------------------------------------


async def test_serve_discover_and_reconcile_round_trip(public_dns: None) -> None:
    """The full loop, spec-mandated end to end. Steps:

    1. A server publishes its card and catalog with `mount_discovery`.
    2. A host probes the domain with `discover_server_cards` under the default policy.
    3. The listing exposes the endpoint dedup key and the listing chain.
    4. The host connects (in memory) and `reconcile_server_card` finds no mismatch,
       because `build_server_card` derived the card from the same identity.
    """
    server = MCPServer(name="weather", version="1.4.0", description="Hourly forecasts.")
    card = build_server_card(
        server,
        name="com.example/weather",
        remotes=[Remote(type="streamable-http", url="https://mcp.example.com/mcp")],
    )
    app = Starlette()
    mount_discovery(app, card, public_url="https://mcp.example.com")

    http_client = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="https://mcp.example.com")
    async with http_client:
        result = await discover_server_cards("https://mcp.example.com/docs", http_client=http_client)
    assert result.failures == []
    (listing,) = result.listings
    assert listing.card.endpoint_urls() == frozenset({"https://mcp.example.com/mcp"})
    assert (listing.listing_domain, listing.hosting_domain) == ("mcp.example.com", "mcp.example.com")

    async with Client(server) as client:
        assert reconcile_server_card(listing.card, client.server_info) == []


async def test_revalidation_round_trip_gets_a_304_from_the_served_card(public_dns: None) -> None:
    """SDK-defined (spec issue #33) end to end: the request/parse pair against the real
    routes turns a stored ETag into a 304, and a fresh fetch into a parsed card."""
    app = Starlette()
    mount_discovery(app, _card(), public_url="https://mcp.example.com")
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://mcp.example.com") as http:
        first = await http.send(create_server_card_request("https://mcp.example.com/mcp/server-card"))
        card = parse_server_card_response(first)
        etag = first.headers["etag"]
        second = await http.send(
            create_server_card_request("https://mcp.example.com/mcp/server-card", if_none_match=etag)
        )
    assert card == _card()
    assert second.status_code == 304


# -- URL helpers -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/any/page?q=1", "https://example.com/.well-known/ai-catalog.json"),
        ("https://example.com:8443", "https://example.com:8443/.well-known/ai-catalog.json"),
        ("http://localhost:8000/mcp", "http://localhost:8000/.well-known/ai-catalog.json"),
    ],
)
def test_well_known_ai_catalog_url_uses_only_the_origin(url: str, expected: str) -> None:
    """Spec-mandated: domain-level discovery reads the origin's well-known path,
    whatever page the input URL pointed at."""
    assert well_known_ai_catalog_url(url) == expected


@pytest.mark.parametrize("url", ["mailto:ops@example.com", "example.com/docs", ""])
def test_well_known_ai_catalog_url_rejects_non_http_input(url: str) -> None:
    """SDK-defined: a URL without an http(s) origin has no well-known path."""
    with pytest.raises(ValueError, match="absolute http"):
        well_known_ai_catalog_url(url)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/mcp", "https://example.com/mcp/server-card"),
        ("https://example.com/mcp/", "https://example.com/mcp/server-card"),
        ("https://example.com:8443/api/mcp", "https://example.com:8443/api/mcp/server-card"),
        ("https://example.com", "https://example.com/server-card"),
    ],
)
def test_server_card_url_appends_the_suffix_to_the_transport_url(url: str, expected: str) -> None:
    """Spec-mandated: the reserved suffix anchors to the streamable HTTP URL, not the
    domain root, with any trailing slash stripped first."""
    assert server_card_url(url) == expected


@pytest.mark.parametrize("url", ["ftp://example.com/mcp", "/mcp"])
def test_server_card_url_rejects_non_http_input(url: str) -> None:
    """SDK-defined: the transport URL must be absolute http(s)."""
    with pytest.raises(ValueError, match="absolute http"):
        server_card_url(url)


# -- load_server_card ---------------------------------------------------------------------------


def test_load_server_card_reads_a_local_file(tmp_path: Path) -> None:
    """SDK-defined: a card can be loaded from disk with no network involved."""
    path = tmp_path / "server-card.json"
    path.write_bytes(_card_bytes())
    assert load_server_card(path) == _card()


def test_load_server_card_missing_file_raises_oserror(tmp_path: Path) -> None:
    """SDK-defined: file problems surface as `OSError`, not as validation noise."""
    with pytest.raises(OSError):
        load_server_card(tmp_path / "absent.json")


def test_load_server_card_invalid_document_raises_validation_error(tmp_path: Path) -> None:
    """SDK-defined: a readable file that is not a card fails validation."""
    path = tmp_path / "server-card.json"
    path.write_text('{"version": "1.0.0"}')
    with pytest.raises(ValidationError):
        load_server_card(path)


# -- request/parse pairs --------------------------------------------------------------------------


def test_create_requests_carry_accept_and_optional_if_none_match() -> None:
    """SDK-defined: the request builders set the media-type Accept header and attach
    `If-None-Match` only when a stored ETag is passed."""
    plain = create_server_card_request("https://example.com/mcp/server-card")
    assert plain.method == "GET"
    assert plain.headers["accept"] == "application/mcp-server-card+json, application/json;q=0.5"
    assert "if-none-match" not in plain.headers

    conditional = create_server_card_request("https://example.com/mcp/server-card", if_none_match='"abc"')
    assert conditional.headers["if-none-match"] == '"abc"'

    catalog_plain = create_ai_catalog_request("https://example.com/.well-known/ai-catalog.json")
    assert catalog_plain.headers["accept"] == "application/ai-catalog+json, application/json;q=0.5"
    assert "if-none-match" not in catalog_plain.headers

    catalog_conditional = create_ai_catalog_request(
        "https://example.com/.well-known/ai-catalog.json", if_none_match='"abc"'
    )
    assert catalog_conditional.headers["if-none-match"] == '"abc"'


def _response(status: int, content: bytes, media_type: str, url: str) -> httpx2.Response:
    return httpx2.Response(
        status,
        content=content,
        headers={"Content-Type": media_type},
        request=httpx2.Request("GET", url),
    )


def test_parse_responses_return_the_documents() -> None:
    """SDK-defined: the parse half applies status and media type checks, then validates."""
    card = parse_server_card_response(_response(200, _card_bytes(), CARD_MEDIA_TYPE, "https://example.com/c"))
    assert card == _card()
    catalog = parse_ai_catalog_response(_response(200, _catalog_bytes([]), CATALOG_MEDIA_TYPE, "https://example.com/w"))
    assert catalog == AICatalog(spec_version="1.0", entries=[])


def test_parse_raises_on_a_304_so_callers_branch_first() -> None:
    """SDK-defined: a 304 has no body to parse. Callers check the status code before
    calling parse, as the revalidation recipe shows."""
    with pytest.raises(DiscoveryError) as exc_info:
        parse_server_card_response(_response(304, b"", CARD_MEDIA_TYPE, "https://example.com/c"))
    assert exc_info.value.reason == "status"


def test_parse_rejects_a_wrong_media_type() -> None:
    """SDK-defined: the media type discipline applies even on caller-owned transports."""
    with pytest.raises(DiscoveryError) as exc_info:
        parse_ai_catalog_response(_response(200, _catalog_bytes([]), "text/html", "https://example.com/w"))
    assert exc_info.value.reason == "media_type"


# -- reconcile_server_card --------------------------------------------------------------------------


def test_reconcile_accepts_the_local_name_part_and_exact_version() -> None:
    """Spec-mandated consistency: `serverInfo.name` matching the card name's post-slash
    local part counts as consistent, and equal versions produce no mismatch."""
    server_info = Implementation(name="weather", version="1.4.0")
    assert reconcile_server_card(_card(), server_info) == []


def test_reconcile_accepts_the_full_namespaced_name() -> None:
    """SDK-defined: a server reporting the full namespaced name is also consistent."""
    server_info = Implementation(name="com.example/weather", version="1.4.0")
    assert reconcile_server_card(_card(), server_info) == []


def test_reconcile_reports_name_and_version_mismatches() -> None:
    """Spec-mandated consistency: disagreements come back as data for logging or UI,
    never as an exception. Runtime values win."""
    server_info = Implementation(name="calendar", version="2.0.0")
    mismatches = reconcile_server_card(_card(), server_info)
    assert [(m.field, m.card_value, m.runtime_value) for m in mismatches] == snapshot(
        [
            ("name", "com.example/weather", "calendar"),
            ("version", "1.4.0", "2.0.0"),
        ]
    )


def test_reconcile_checks_the_protocol_version_against_declared_unions() -> None:
    """SDK-defined: with `protocol_version=` given, the union of every remote's declared
    `supportedProtocolVersions` is consulted. A member passes, a stranger mismatches."""
    card = ServerCard(
        name="com.example/weather",
        version="1.4.0",
        description="Hourly forecasts.",
        remotes=[
            Remote(type="streamable-http", url="https://a.example.com/mcp", supported_protocol_versions=["2025-06-18"]),
            Remote(type="sse", url="https://b.example.com/sse", supported_protocol_versions=["2025-11-25"]),
        ],
    )
    server_info = Implementation(name="weather", version="1.4.0")
    assert reconcile_server_card(card, server_info, protocol_version="2025-11-25") == []
    mismatches = reconcile_server_card(card, server_info, protocol_version="2026-07-28")
    assert [(m.field, m.card_value, m.runtime_value) for m in mismatches] == snapshot(
        [("protocol_versions", "2025-06-18, 2025-11-25", "2026-07-28")]
    )


def test_reconcile_skips_the_protocol_check_without_declared_versions() -> None:
    """SDK-defined: a card whose remotes declare no protocol versions makes no claim, so
    any negotiated version is consistent."""
    server_info = Implementation(name="weather", version="1.4.0")
    assert reconcile_server_card(_card(), server_info, protocol_version="2026-07-28") == []


async def test_discover_records_a_failure_for_an_unreachable_nested_catalog(public_dns: None) -> None:
    """SDK-defined (best practices): a nested catalog that cannot be fetched becomes a
    failure entry, and the probe still returns."""
    nested = {
        "identifier": "urn:air:example.com:catalog:gone",
        "type": CATALOG_MEDIA_TYPE,
        "url": "https://example.com/gone.json",
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/.well-known/ai-catalog.json":
            return httpx2.Response(200, content=_catalog_bytes([nested]), headers={"Content-Type": CATALOG_MEDIA_TYPE})
        return httpx2.Response(404)

    async with _mock_client(handler) as client:
        result = await discover_server_cards("https://example.com", http_client=client)
    assert result.listings == []
    (failure,) = result.failures
    assert failure.entry_identifier == "urn:air:example.com:catalog:gone"
    assert isinstance(failure.error, DiscoveryError)
    assert failure.error.reason == "status"
