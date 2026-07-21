"""Hardened HTTP core for discovery fetches. Private module.

Every network fetch (including every redirect hop and every nested catalog
follow) is re-admitted under the same rules: http(s) scheme only, plain http
only to loopback hosts, an SSRF address guard checked before the request,
bounded redirects, a streamed response size cap, and a media type check.
"""

import ipaddress
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlsplit

import anyio
import httpx2

from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.experimental._base import is_loopback_host
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
    """

    max_response_bytes: int = 1_048_576
    max_redirects: int = 3
    max_catalog_entries: int = 100
    max_catalog_depth: int = MAX_CATALOG_NESTING_DEPTH
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
    if address.version == 4 and address in _CGNAT_NETWORK:
        return True
    # is_private covers loopback, RFC 1918, ULA and the unspecified address.
    return address.is_private or address.is_link_local or address.is_multicast or address.is_reserved


async def _admit_url(url: str, policy: DiscoveryPolicy) -> None:
    """Apply the scheme rule and the SSRF address guard to one fetch target.

    Raises:
        DiscoveryError: `reason="insecure_transport"` for a non-http(s) URL or
            plain http to a non-loopback host, `reason="blocked_address"` when
            the host is (or resolves to) a non-public address.
    """
    parts = urlsplit(url)
    host = parts.hostname
    if parts.scheme not in ("http", "https") or not host:
        raise DiscoveryError(
            f"discovery requires an absolute http(s) URL, got {url!r}", url=url, reason="insecure_transport"
        )
    if policy.allow_private_addresses:
        return
    if parts.scheme == "http" and not is_loopback_host(host):
        raise DiscoveryError(
            f"plain http is only allowed for loopback hosts, got {url!r}", url=url, reason="insecure_transport"
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
            headers = {"Accept": f"{media_type}, application/json;q=0.5"}
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
