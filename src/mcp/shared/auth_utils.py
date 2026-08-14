"""Utilities for OAuth 2.0 Resource Indicators (RFC 8707) and PKCE (RFC 7636)."""

import posixpath
import re
import time
from urllib.parse import urlparse, urlsplit, urlunsplit

from pydantic import AnyUrl, HttpUrl


def _normalize_resource_path(path: str) -> str:
    """Resolve dot-segments without decoding encoded path separators."""
    has_trailing_slash = path.endswith("/")

    # RFC 3986 treats percent-encoded unreserved characters as equivalent. Decode
    # only encoded dots here: unquoting the whole path would turn %2F into a
    # separator and change the resource hierarchy being authorized.
    path = re.sub(r"%2e", ".", path, flags=re.IGNORECASE)
    path = posixpath.normpath(path)
    if path == ".":
        path = ""

    if has_trailing_slash and not path.endswith("/"):
        path += "/"
    return path


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

    # Resolve dot-segments before normalizing trailing slashes so that a
    # resource cannot escape its configured path through ../ or its encoded
    # equivalent.
    requested_path = _normalize_resource_path(requested.path)
    configured_path = _normalize_resource_path(configured.path)

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
