"""Discover, fetch and reconcile Server Cards (experimental, tracks SEP-2127).

Discovery is host-invoked only. Nothing here runs implicitly, connects to a
discovered server, persists anything or asks for consent. Those are host
application decisions. `CardListing` carries the listing chain (listing
domain versus hosting domain) for consent UI, and
`ServerCard.endpoint_urls()` is the dedup key.

Card contents are advisory. Runtime values win, and cards MUST NOT drive
security or access-control decisions.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx2
import pydantic
from mcp_types import Implementation

from mcp.client.experimental._discovery_http import (
    DiscoveryError,
    DiscoveryErrorReason,
    DiscoveryPolicy,
    accept_header,
    check_media_type,
    check_status,
    fetch_discovery_document,
)
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.experimental.ai_catalog import (
    AI_CATALOG_MEDIA_TYPE,
    AI_CATALOG_WELL_KNOWN_PATH,
    AICatalog,
    CatalogEntry,
)
from mcp.shared.experimental.server_card import RESERVED_SERVER_CARD_SUFFIX, SERVER_CARD_MEDIA_TYPE, ServerCard

__all__ = [
    "DiscoveryPolicy",
    "DiscoveryError",
    "DiscoveryErrorReason",
    "CardListing",
    "DiscoveryFailure",
    "DiscoveryResult",
    "CardMismatch",
    "fetch_server_card",
    "fetch_ai_catalog",
    "discover_server_cards",
    "load_server_card",
    "well_known_ai_catalog_url",
    "server_card_url",
    "create_server_card_request",
    "parse_server_card_response",
    "create_ai_catalog_request",
    "parse_ai_catalog_response",
    "reconcile_server_card",
]

_SERVER_CARD_ACCEPT = accept_header(SERVER_CARD_MEDIA_TYPE)
_AI_CATALOG_ACCEPT = accept_header(AI_CATALOG_MEDIA_TYPE)


def _display_host(url: str) -> str:
    """The host (plus `:port` when present) of `url`, never its userinfo.

    `netloc` would include a `user@` prefix, which a hostile catalog can use
    to make `github.com@evil.example` read as a trusted brand in consent UI.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:  # bare IPv6 from .hostname; re-bracket so the port reads unambiguously
        host = f"[{host}]"
    return f"{host}:{parts.port}" if parts.port is not None else host


@dataclass(frozen=True, slots=True)
class CardListing:
    """One discovered card together with where it was listed and hosted.

    A listing is an unverified assertion. Show both domains in consent UI:
    they differ whenever a catalog lists a card hosted elsewhere.
    """

    card: ServerCard
    entry: CatalogEntry
    catalog_url: str
    card_url: str | None

    @property
    def listing_domain(self) -> str:
        """Host (plus `:port` when present) of the catalog that listed the card."""
        return _display_host(self.catalog_url)

    @property
    def hosting_domain(self) -> str | None:
        """Host the card was fetched from, or None for an inline `data` entry."""
        return _display_host(self.card_url) if self.card_url is not None else None


@dataclass(frozen=True, slots=True)
class DiscoveryFailure:
    """One catalog entry (or nested catalog) that could not be turned into a listing."""

    url: str | None
    entry_identifier: str | None
    error: Exception


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Everything one discovery probe produced.

    A bad entry never kills the probe. It lands in `failures` while the
    other entries still produce `listings`.
    """

    listings: list[CardListing]
    failures: list[DiscoveryFailure]


@dataclass(frozen=True, slots=True)
class CardMismatch:
    """One advisory discrepancy between a card claim and a runtime value."""

    field: str
    card_value: str | None
    runtime_value: str | None


def well_known_ai_catalog_url(url: str) -> str:
    """The well-known catalog URL for the origin of any http(s) URL.

    Raises:
        ValueError: If `url` is not absolute http(s).
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"expected an absolute http(s) URL, got {url!r}")
    return f"{parts.scheme}://{parts.netloc}{AI_CATALOG_WELL_KNOWN_PATH}"


def server_card_url(streamable_http_url: str) -> str:
    """The spec-reserved card URL for a streamable HTTP transport URL.

    The suffix is appended to the transport URL, not the domain root:
    `https://host/mcp` becomes `https://host/mcp/server-card`.

    Raises:
        ValueError: If `streamable_http_url` is not absolute http(s).
    """
    parts = urlsplit(streamable_http_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"expected an absolute http(s) URL, got {streamable_http_url!r}")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}{RESERVED_SERVER_CARD_SUFFIX}"


def load_server_card(path: str | os.PathLike[str]) -> ServerCard:
    """Parse a Server Card from a local file. No network is involved.

    Raises:
        OSError: If the file cannot be read.
        pydantic.ValidationError: If the document is not a valid card.
    """
    return ServerCard.model_validate_json(Path(path).read_bytes())


async def fetch_server_card(
    url: str,
    *,
    http_client: httpx2.AsyncClient | None = None,
    policy: DiscoveryPolicy | None = None,
) -> ServerCard:
    """Fetch and parse a Server Card from `url` under `policy`.

    A missing `$schema` is defaulted on ingestion. A wrong one is rejected.
    Avoid passing an `http_client` that carries cookies or ambient
    credentials. Discovery requests must never send any.

    Raises:
        DiscoveryError: When a policy rule fails (status, media type, size,
            redirects, blocked address, insecure transport).
        pydantic.ValidationError: If the document is not a valid card.
        httpx2.HTTPError: For raw connection failures.
        OSError: When DNS resolution fails (an unresolvable host raises
            `socket.gaierror` from the address guard, before any request).
        TimeoutError: When the fetch exceeds `policy.timeout_seconds`.
    """
    body = await fetch_discovery_document(url, SERVER_CARD_MEDIA_TYPE, http_client=http_client, policy=policy)
    return ServerCard.model_validate_json(body)


async def fetch_ai_catalog(
    url: str,
    *,
    http_client: httpx2.AsyncClient | None = None,
    policy: DiscoveryPolicy | None = None,
) -> AICatalog:
    """Fetch and parse an AI Catalog from `url` under `policy`.

    Raises:
        DiscoveryError: When a policy rule fails.
        pydantic.ValidationError: If the document is not a valid catalog.
        httpx2.HTTPError: For raw connection failures.
        OSError: When DNS resolution fails (an unresolvable host raises
            `socket.gaierror` from the address guard, before any request).
        TimeoutError: When the fetch exceeds `policy.timeout_seconds`.
    """
    body = await fetch_discovery_document(url, AI_CATALOG_MEDIA_TYPE, http_client=http_client, policy=policy)
    return AICatalog.model_validate_json(body)


@dataclass(slots=True)
class _ProbeState:
    """Mutable per-probe budget shared by every catalog one probe walks.

    `max_catalog_entries` and `max_catalog_depth` cap one document and the
    nesting, but their product is multiplicative, so a hostile catalog tree
    could otherwise amplify one probe into ~`entries**depth` fetches. The
    aggregate entry budget and the visited set bound the whole walk.
    """

    entries_remaining: int
    visited_catalog_urls: set[str]
    exhausted: bool = False

    def take_entry(self, catalog_url: str, policy: DiscoveryPolicy, failures: list[DiscoveryFailure]) -> bool:
        """Consume one unit of budget, recording a single failure when it runs out."""
        if self.entries_remaining > 0:
            self.entries_remaining -= 1
            return True
        self.exhausted = True
        error = DiscoveryError(
            f"probe exceeded the budget of {policy.max_probe_entries} catalog entries",
            url=catalog_url,
            reason="probe_budget",
        )
        failures.append(DiscoveryFailure(url=catalog_url, entry_identifier=None, error=error))
        return False


# The per-entry safety net: one hostile or broken entry becomes a failure, never
# a probe-killer. OSError subsumes socket.gaierror (the address guard resolves
# DNS itself) and TimeoutError (the per-fetch deadline).
_PER_ENTRY_ERRORS = (DiscoveryError, httpx2.HTTPError, OSError, pydantic.ValidationError)


async def _collect_card(
    client: httpx2.AsyncClient,
    entry: CatalogEntry,
    catalog_url: str,
    policy: DiscoveryPolicy,
    listings: list[CardListing],
    failures: list[DiscoveryFailure],
) -> None:
    """Turn one card entry into a listing, or record why it could not be."""
    try:
        if entry.url is not None:
            card = await fetch_server_card(entry.url, http_client=client, policy=policy)
            card_url = entry.url
        else:
            card = ServerCard.model_validate(entry.data)
            card_url = None
    except _PER_ENTRY_ERRORS as error:
        failures.append(DiscoveryFailure(url=entry.url, entry_identifier=entry.identifier, error=error))
        return
    listings.append(CardListing(card=card, entry=entry, catalog_url=catalog_url, card_url=card_url))


async def _collect_nested_catalog(
    client: httpx2.AsyncClient,
    entry: CatalogEntry,
    catalog_url: str,
    depth: int,
    policy: DiscoveryPolicy,
    state: _ProbeState,
    listings: list[CardListing],
    failures: list[DiscoveryFailure],
) -> None:
    """Follow one nested catalog entry, or record why it could not be."""
    if entry.url is not None and entry.url in state.visited_catalog_urls:
        return  # already walked: a legitimate duplicate adds nothing, a cycle never terminates
    if depth > policy.max_catalog_depth:
        error = DiscoveryError(
            f"nested catalog exceeds the depth cap of {policy.max_catalog_depth}",
            url=entry.url if entry.url is not None else catalog_url,
            reason="catalog_depth",
        )
        failures.append(DiscoveryFailure(url=entry.url, entry_identifier=entry.identifier, error=error))
        return
    try:
        if entry.url is not None:
            state.visited_catalog_urls.add(entry.url)
            nested = await fetch_ai_catalog(entry.url, http_client=client, policy=policy)
            nested_url = entry.url
        else:
            nested = AICatalog.model_validate(entry.data)
            nested_url = catalog_url
    except _PER_ENTRY_ERRORS as error:
        failures.append(DiscoveryFailure(url=entry.url, entry_identifier=entry.identifier, error=error))
        return
    await _walk_catalog(client, nested, nested_url, depth, policy, state, listings, failures)


async def _walk_catalog(
    client: httpx2.AsyncClient,
    catalog: AICatalog,
    catalog_url: str,
    depth: int,
    policy: DiscoveryPolicy,
    state: _ProbeState,
    listings: list[CardListing],
    failures: list[DiscoveryFailure],
) -> None:
    """Collect card listings from one catalog document, recursing into nested ones."""
    entries = catalog.entries
    if len(entries) > policy.max_catalog_entries:
        error = DiscoveryError(
            f"catalog lists {len(entries)} entries; only the first {policy.max_catalog_entries} were processed",
            url=catalog_url,
            reason="invalid_entry",
        )
        failures.append(DiscoveryFailure(url=catalog_url, entry_identifier=None, error=error))
        entries = entries[: policy.max_catalog_entries]
    for entry in entries:
        if entry.type not in (SERVER_CARD_MEDIA_TYPE, AI_CATALOG_MEDIA_TYPE):
            continue  # Other artifact types are not failures. Catalogs legitimately advertise them.
        if state.exhausted:
            return  # a nested walk already recorded the budget failure; add no more noise
        if not state.take_entry(catalog_url, policy, failures):
            return
        if entry.type == SERVER_CARD_MEDIA_TYPE:
            await _collect_card(client, entry, catalog_url, policy, listings, failures)
        else:
            await _collect_nested_catalog(client, entry, catalog_url, depth + 1, policy, state, listings, failures)


async def _probe(
    client: httpx2.AsyncClient,
    catalog_url: str,
    policy: DiscoveryPolicy,
) -> DiscoveryResult:
    """Fetch the top-level catalog and walk it under one shared budget."""
    catalog = await fetch_ai_catalog(catalog_url, http_client=client, policy=policy)
    state = _ProbeState(entries_remaining=policy.max_probe_entries, visited_catalog_urls={catalog_url})
    listings: list[CardListing] = []
    failures: list[DiscoveryFailure] = []
    await _walk_catalog(client, catalog, catalog_url, 1, policy, state, listings, failures)
    return DiscoveryResult(listings=listings, failures=failures)


async def discover_server_cards(
    url: str,
    *,
    http_client: httpx2.AsyncClient | None = None,
    policy: DiscoveryPolicy | None = None,
) -> DiscoveryResult:
    """One discovery probe: the well-known catalog of `url`'s origin, then its cards.

    Any user-entered URL works. Only its origin is used. The probe fetches
    the catalog, follows card entries (by URL or inline `data`) and nested
    catalogs up to `policy.max_catalog_depth`, and collects per-entry
    failures instead of raising them. Already-visited catalog URLs are never
    refetched, and `policy.max_probe_entries` bounds the whole walk, so a
    hostile catalog tree cannot amplify one probe into unbounded fetches.
    Nothing is deduplicated across listings, connected to or persisted.
    Enterprise controls (disabling or allowlisting discovery) stay trivial
    because the probe only runs when the host calls it.

    Raises:
        ValueError: If `url` is not absolute http(s).
        DiscoveryError: When fetching the top-level catalog itself fails a
            policy rule. Per-entry failures are collected, never raised.
        pydantic.ValidationError: If the top-level catalog is malformed.
        httpx2.HTTPError: For raw connection failures on the top-level fetch.
        OSError: When DNS resolution fails for the top-level catalog host
            (an unresolvable host raises `socket.gaierror`).
        TimeoutError: When the top-level fetch exceeds `policy.timeout_seconds`.
    """
    resolved_policy = policy if policy is not None else DiscoveryPolicy()
    catalog_url = well_known_ai_catalog_url(url)
    if http_client is None:
        # One fresh credential-free client for the whole walk, so a large
        # catalog reuses connections instead of a TLS handshake per entry.
        async with create_mcp_http_client() as own_client:
            return await _probe(own_client, catalog_url, resolved_policy)
    return await _probe(http_client, catalog_url, resolved_policy)


def create_server_card_request(url: str, *, if_none_match: str | None = None) -> httpx2.Request:
    """A GET request for a card, with the Accept header and optional `If-None-Match`.

    Together with `parse_server_card_response` this is the revalidation
    toolkit for hosts that keep their own cache: send the stored ETag, and an
    unchanged card costs a 304. The SDK deliberately ships no cache storage.
    """
    headers = {"Accept": _SERVER_CARD_ACCEPT}
    if if_none_match is not None:
        headers["If-None-Match"] = if_none_match
    return httpx2.Request("GET", url, headers=headers)


def parse_server_card_response(response: httpx2.Response) -> ServerCard:
    """Parse a card from a response the caller transported.

    Only status, media type and document shape are checked here. The caller
    owns the transport, so no size or address rules apply. A 304 raises.
    Branch on `response.status_code == 304` before parsing.

    Raises:
        DiscoveryError: For a non-2xx status (including 304) or a wrong media type.
        pydantic.ValidationError: If the document is not a valid card.
    """
    url = str(response.request.url)
    check_status(response, url)
    check_media_type(response, url, SERVER_CARD_MEDIA_TYPE)
    return ServerCard.model_validate_json(response.content)


def create_ai_catalog_request(url: str, *, if_none_match: str | None = None) -> httpx2.Request:
    """A GET request for a catalog, with the Accept header and optional `If-None-Match`."""
    headers = {"Accept": _AI_CATALOG_ACCEPT}
    if if_none_match is not None:
        headers["If-None-Match"] = if_none_match
    return httpx2.Request("GET", url, headers=headers)


def parse_ai_catalog_response(response: httpx2.Response) -> AICatalog:
    """Parse a catalog from a response the caller transported.

    Raises:
        DiscoveryError: For a non-2xx status (including 304) or a wrong media type.
        pydantic.ValidationError: If the document is not a valid catalog.
    """
    url = str(response.request.url)
    check_status(response, url)
    check_media_type(response, url, AI_CATALOG_MEDIA_TYPE)
    return AICatalog.model_validate_json(response.content)


def reconcile_server_card(
    card: ServerCard,
    server_info: Implementation,
    *,
    protocol_version: str | None = None,
) -> list[CardMismatch]:
    """Compare card claims to live values. Advisory only, never raises.

    Call it with `Client.server_info` after connecting. It returns
    discrepancies for logging or UI. Runtime values MUST win, and cards MUST
    NOT drive security or access-control decisions. The card name matches
    when `server_info.name` equals either the full namespaced name or its
    post-slash local part.
    """
    mismatches: list[CardMismatch] = []
    local_name = card.name.split("/", 1)[1]
    if server_info.name not in (card.name, local_name):
        mismatches.append(CardMismatch(field="name", card_value=card.name, runtime_value=server_info.name))
    if server_info.version != card.version:
        mismatches.append(CardMismatch(field="version", card_value=card.version, runtime_value=server_info.version))
    if protocol_version is not None:
        declared = {version for remote in card.remotes or [] for version in remote.supported_protocol_versions or []}
        if declared and protocol_version not in declared:
            mismatches.append(
                CardMismatch(
                    field="protocol_versions",
                    card_value=", ".join(sorted(declared)),
                    runtime_value=protocol_version,
                )
            )
    return mismatches
