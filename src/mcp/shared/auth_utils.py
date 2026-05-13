"""Utilities for OAuth 2.0 Resource Indicators (RFC 8707) and PKCE (RFC 7636)."""

import posixpath
import time
from urllib.parse import unquote, urlparse, urlsplit, urlunsplit

from pydantic import AnyUrl, HttpUrl


def _normalize_url_path(path: str) -> str:
    """Decode percent-encoding and resolve dot-segments in a URL path.

    Used by check_resource_allowed to ensure hierarchical matching operates on
    normalized paths. Without normalization, a path like "/api/../admin" would
    satisfy startswith("/api") even though the resolved path is "/admin",
    enabling a confused-deputy attack at downstream resource servers that DO
    normalize paths.

    - unquote() decodes percent-encoded segments so "%2e%2e" -> ".." cannot
      bypass the normalization step.
    - posixpath.normpath() resolves "." and ".." segments to canonical form.

    Returns a path that ends with "/" if the original did, so trailing-slash
    semantics are preserved.
    """
    decoded = unquote(path)
    normalized = posixpath.normpath(decoded) if decoded else decoded
    # posixpath.normpath collapses "//" to "/" and strips trailing slashes.
    # Restore trailing slash only if the original path ended with one AND the
    # normalized form is non-empty (avoid producing "//" for root paths).
    if path.endswith("/") and normalized != "/" and not normalized.endswith("/"):
        normalized += "/"
    return normalized


def resource_url_from_server_url(url: str | HttpUrl | AnyUrl) -> str:
    """Convert server URL to canonical resource URL per RFC 8707.

    RFC 8707 section 2 states that resource URIs "MUST NOT include a fragment component".
    Returns absolute URI with lowercase scheme/host for canonical form.

    Args:
        url: Server URL to convert

    Returns:
        Canonical resource URL string
    """
    # Convert to string if needed
    url_str = str(url)

    # Parse the URL and remove fragment, create canonical form
    parsed = urlsplit(url_str)
    canonical = urlunsplit(parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower(), fragment=""))

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
    # Parse both URLs
    requested = urlparse(requested_resource)
    configured = urlparse(configured_resource)

    # Compare scheme, host, and port (origin)
    if requested.scheme.lower() != configured.scheme.lower() or requested.netloc.lower() != configured.netloc.lower():
        return False

    # Normalize paths: decode percent-encoding and resolve dot-segments before
    # comparison. This prevents bypass via "/api/../admin" (resolves to
    # "/admin", not a child of "/api") and "/api/%2e%2e/admin" (URL-encoded
    # equivalent). Without this, downstream resource servers that DO normalize
    # paths would interpret the access as "/admin" while the auth check passed
    # against the literal "/api/.." prefix.
    requested_path = _normalize_url_path(requested.path)
    configured_path = _normalize_url_path(configured.path)

    # Normalize trailing slashes before comparison so that
    # "/foo" and "/foo/" are treated as equivalent.
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
