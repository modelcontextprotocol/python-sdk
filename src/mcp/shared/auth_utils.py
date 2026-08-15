"""Utilities for OAuth 2.0 Resource Indicators (RFC 8707) and PKCE (RFC 7636)."""

import time
from urllib.parse import SplitResult, urlparse, urlsplit, urlunsplit

from pydantic import AnyUrl, HttpUrl


def _canonical_netloc(parsed: SplitResult) -> str:
    """Normalize netloc by lowercasing and stripping explicit default ports (RFC 3986 §6.2.3)."""
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    port = parsed.port

    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        # Strip default port while preserving userinfo and IPv6 brackets
        userinfo = ""
        if "@" in netloc:
            userinfo = netloc.split("@", 1)[0] + "@"
        hostname = parsed.hostname.lower() if parsed.hostname else ""
        if ":" in hostname:  # IPv6 literal
            hostname = f"[{hostname}]"
        return f"{userinfo}{hostname}"
    return netloc


def resource_url_from_server_url(url: str | HttpUrl | AnyUrl) -> str:
    """Convert server URL to canonical resource URL per RFC 8707.

    RFC 8707 section 2 states that resource URIs "MUST NOT include a fragment component".
    RFC 3986 section 6.2.3 specifies normalization of default ports (80 for http, 443 for https).
    Returns absolute URI with lowercase scheme/host and stripped default ports for canonical form.

    Args:
        url: Server URL to convert

    Returns:
        Canonical resource URL string
    """
    # Convert to string if needed
    url_str = str(url)

    # Parse the URL and remove fragment, create canonical form
    parsed = urlsplit(url_str)
    canonical_netloc = _canonical_netloc(parsed)
    canonical = urlunsplit(parsed._replace(scheme=parsed.scheme.lower(), netloc=canonical_netloc, fragment=""))

    return canonical


def check_resource_allowed(requested_resource: str, configured_resource: str) -> bool:
    """Check if a requested resource URL matches a configured resource URL.

    A requested resource matches if it has the same scheme, domain, port,
    and its path starts with the configured resource's path. This allows
    hierarchical matching where a token for a parent resource can be used
    for child resources.

    Args:
        requested_resource: The resource URL being requested
        configured_resource: The resource URL that has been configured

    Returns:
        True if the requested resource matches the configured resource
    """
    # Canonicalize both resource URLs (RFC 8707 & RFC 3986 default port normalization)
    requested_canonical = resource_url_from_server_url(requested_resource)
    configured_canonical = resource_url_from_server_url(configured_resource)

    # Parse both canonical URLs
    requested = urlparse(requested_canonical)
    configured = urlparse(configured_canonical)

    # Compare scheme, host, and port (origin)
    if requested.scheme.lower() != configured.scheme.lower() or requested.netloc.lower() != configured.netloc.lower():
        return False

    # Normalize trailing slashes before comparison so that
    # "/foo" and "/foo/" are treated as equivalent.
    requested_path = requested.path
    configured_path = configured.path
    if not requested_path.endswith("/"):
        requested_path += "/"
    if not configured_path.endswith("/"):
        configured_path += "/"

    # Check hierarchical match: requested must start with configured path.
    # The trailing-slash normalization ensures "/api123/" won't match "/api/".
    return requested_path.startswith(configured_path)


def calculate_token_expiry(expires_in: int | str | None) -> float | None:
    """Calculate token expiry timestamp from expires_in seconds.

    Args:
        expires_in: Seconds until token expiration (may be string from some servers)

    Returns:
        Unix timestamp when token expires, or None if no expiry specified
    """
    if expires_in is None:
        return None  # pragma: no cover
    # Defensive: handle servers that return expires_in as string
    return time.time() + int(expires_in)
