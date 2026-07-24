"""Hardened HTTP core for discovery fetches. Private module.

Every network fetch (including every redirect hop and every nested catalog
follow) is re-admitted under the same rules: http(s) scheme only, no userinfo,
plain http only under `allow_private_addresses`, an SSRF address guard checked
before the request, bounded redirects, a streamed response size cap, and a
media type check.
"""

import ipaddress
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlsplit

import anyio
import httpx2

from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.experimental.ai_catalog import MAX_CATALOG_NESTING_DEPTH

DiscoveryErrorReason = Literal[
    "status",
    "media_type",
    "response_too_large",
    "too_many_redirects",
    "blocked_address",
    "insecure_transport",
    "invalid_entry",
    "catalog_depth",
    "probe_budget",
]

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


@dataclass(frozen=True, slots=True, kw_only=True)
class DiscoveryPolicy:
    """Limits applied to every discovery fetch.

    The defaults are the hardened production posture. Set
    `allow_private_addresses=True` for local development, which permits plain
    http and skips the address guard entirely.

    The address guard resolves DNS before the request and re-checks every
    redirect hop, but the HTTP client re-resolves when it connects, so a
    DNS rebinding race remains possible between the check and the connect.

    `max_catalog_entries` caps one catalog document and `max_catalog_depth`
    caps nesting, but neither bounds their product, so `max_probe_entries` is
    the aggregate budget: the total card and nested-catalog entries one
    discovery probe will process across every catalog it walks. A probe that
    exhausts it records a single `probe_budget` failure and returns what it
    has, which also bounds the probe's total fetches and worst-case duration
    (`max_probe_entries * timeout_seconds`).
    """

    max_response_bytes: int = 1_048_576
    max_redirects: int = 3
    max_catalog_entries: int = 100
    max_catalog_depth: int = MAX_CATALOG_NESTING_DEPTH
    max_probe_entries: int = 500
    allow_private_addresses: bool = False
    timeout_seconds: float = 10.0


class DiscoveryError(Exception):
    """A transport or policy failure during discovery.

    `reason` states which rule failed and `url` names the offending target.
    Document shape failures raise `pydantic.ValidationError` instead, and raw
    connection failures stay `httpx2.HTTPError`.
    """

    url: str
    reason: DiscoveryErrorReason

    def __init__(self, message: str, *, url: str, reason: DiscoveryErrorReason) -> None:
        super().__init__(message)
        self.url = url
        self.reason = reason


def accept_header(media_type: str) -> str:
    """The Accept header for one discovery media type.

    The canonical type is preferred, with plain `application/json` at a lower
    quality because static hosts and CDNs commonly serve it. This is the one
    place the lenience is written down; `check_media_type` mirrors it.
    """
    return f"{media_type}, application/json;q=0.5"


def check_status(response: httpx2.Response, url: str) -> None:
    """Reject any non-2xx response.

    Raises:
        DiscoveryError: With `reason="status"`, chaining the underlying
            `httpx2.HTTPStatusError`.
    """
    try:
        response.raise_for_status()
    except httpx2.HTTPStatusError as exc:
        raise DiscoveryError(f"unexpected status {response.status_code} from {url}", url=url, reason="status") from exc


def check_media_type(response: httpx2.Response, url: str, expected: str) -> None:
    """Reject a response whose media type is neither `expected` nor JSON.

    Plain `application/json` is accepted because static hosts and CDNs
    commonly serve it.

    Raises:
        DiscoveryError: With `reason="media_type"`.
    """
    content_type = response.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in (expected, "application/json"):
        raise DiscoveryError(f"unexpected media type {content_type!r} from {url}", url=url, reason="media_type")


async def _host_addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """The IP addresses `host` names: the literal itself, or its DNS resolution."""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        infos = await anyio.getaddrinfo(host, None)
        # sockaddr[0] is the address; IPv6 link-local entries carry a %scope suffix.
        return [ipaddress.ip_address(info[4][0].split("%", 1)[0]) for info in infos]


def _is_blocked_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether `address` is off-limits for discovery: anything not publicly routable."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        # Judge `::ffff:a.b.c.d` by its embedded IPv4 rules. Relying on the v6
        # properties would miss CGNAT everywhere and, before the gh-113171
        # ipaddress fix, the private v4 ranges too.
        address = address.ipv4_mapped
    if address.version == 4 and address in _CGNAT_NETWORK:
        return True
    # is_private covers loopback, RFC 1918, ULA and the unspecified address.
    return address.is_private or address.is_link_local or address.is_multicast or address.is_reserved


async def _admit_url(url: str, policy: DiscoveryPolicy) -> None:
    """Apply the scheme rule and the SSRF address guard to one fetch target.

    Raises:
        DiscoveryError: `reason="insecure_transport"` for a non-http(s) URL, a
            URL carrying userinfo, or plain http under the hardened policy,
            `reason="blocked_address"` when the host is (or resolves to) a
            non-public address.
    """
    parts = urlsplit(url)
    host = parts.hostname
    if parts.scheme not in ("http", "https") or not host:
        raise DiscoveryError(
            f"discovery requires an absolute http(s) URL, got {url!r}", url=url, reason="insecure_transport"
        )
    if "@" in parts.netloc:
        # Discovery never sends credentials, and `user@host` URLs exist mainly
        # to make a hostile target read as a trusted brand in consent UI.
        raise DiscoveryError(
            f"discovery URLs must not carry userinfo, got {url!r}", url=url, reason="insecure_transport"
        )
    if policy.allow_private_addresses:
        return
    if parts.scheme == "http":
        # Under the hardened policy loopback targets are blocked by the
        # address guard anyway, so plain http (loopback included) never
        # survives it; local development opts in via allow_private_addresses.
        raise DiscoveryError(
            f"plain http is only allowed with allow_private_addresses=True, got {url!r}",
            url=url,
            reason="insecure_transport",
        )
    for address in await _host_addresses(host):
        if _is_blocked_address(address):
            raise DiscoveryError(f"{url!r} points at blocked address {address}", url=url, reason="blocked_address")


async def _read_limited(response: httpx2.Response, url: str, policy: DiscoveryPolicy) -> bytes:
    """Stream the body, failing as soon as it exceeds the size cap."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > policy.max_response_bytes:
            raise DiscoveryError(
                f"response from {url} exceeds {policy.max_response_bytes} bytes", url=url, reason="response_too_large"
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _fetch(client: httpx2.AsyncClient, url: str, media_type: str, policy: DiscoveryPolicy) -> bytes:
    """One admitted fetch, walking redirects manually so each hop is re-checked."""
    with anyio.fail_after(policy.timeout_seconds):
        current = url
        for _ in range(policy.max_redirects + 1):
            await _admit_url(current, policy)
            headers = {"Accept": accept_header(media_type)}
            request = client.build_request("GET", current, headers=headers)
            response = await client.send(request, stream=True, follow_redirects=False)
            try:
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if location is None:
                        raise DiscoveryError(
                            f"redirect from {current} carries no Location", url=current, reason="status"
                        )
                    current = urljoin(current, location)
                    continue
                check_status(response, current)
                check_media_type(response, current, media_type)
                return await _read_limited(response, current, policy)
            finally:
                await response.aclose()
        raise DiscoveryError(
            f"more than {policy.max_redirects} redirects while fetching {url}", url=current, reason="too_many_redirects"
        )


async def fetch_discovery_document(
    url: str,
    media_type: str,
    *,
    http_client: httpx2.AsyncClient | None = None,
    policy: DiscoveryPolicy | None = None,
) -> bytes:
    """Fetch one discovery document under `policy`, returning its raw bytes.

    With `http_client=None` a fresh client is created per call, so no cookies
    or ambient credentials ever accompany a discovery request. A caller-owned
    client still gets every URL, redirect, size and media type check.

    Raises:
        DiscoveryError: When any policy rule fails.
        httpx2.HTTPError: For raw connection failures.
        OSError: When DNS resolution itself fails.
        TimeoutError: When the fetch exceeds `policy.timeout_seconds`.
    """
    resolved_policy = policy if policy is not None else DiscoveryPolicy()
    if http_client is None:
        async with create_mcp_http_client() as own_client:
            return await _fetch(own_client, url, media_type, resolved_policy)
    return await _fetch(http_client, url, media_type, resolved_policy)
