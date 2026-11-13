"""Utilities for OAuth 2.0 Resource Indicators (RFC 8707) and PKCE (RFC 7636)."""

import time
from collections.abc import Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from pydantic import AnyUrl, HttpUrl


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


def add_query_params(url: str, params: Mapping[str, str]) -> str:
    """Append query parameters to a URL, preserving any existing ones.

    New parameters are appended after the existing query rather than replacing
    keys that are already present, so a key may end up appearing more than once.
    The whole query string is re-encoded, which can change how existing
    parameters are escaped (e.g. ``%20`` becomes ``+``).

    Args:
        url: URL to add the parameters to
        params: Mapping of parameter names to values to append

    Returns:
        The URL with the parameters appended to its query string
    """
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.extend(params.items())
    return urlunsplit(parts._replace(query=urlencode(query)))


def remove_query_params(url: str, keys: Iterable[str]) -> str:
    """Remove query parameters from a URL by name.

    Every occurrence of each named key is removed; other parameters keep their
    original order. The remaining query string is re-encoded, which can change
    how those parameters are escaped (e.g. ``%20`` becomes ``+``).

    Args:
        url: URL to remove the parameters from
        keys: Iterable of parameter names to remove

    Returns:
        The URL without the named query parameters
    """
    keys = set(keys)
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in keys]
    return urlunsplit(parts._replace(query=urlencode(query)))


def replace_query_params(url: str, params: Mapping[str, str]) -> str:
    """Set query parameters on a URL, replacing any existing values for those keys.

    Other existing parameters are retained in order, and each given key appears
    exactly once, after the retained parameters. The whole query string is
    re-encoded, which can change how existing parameters are escaped (e.g.
    ``%20`` becomes ``+``).

    Args:
        url: URL to set the parameters on
        params: Mapping of parameter names to values to set

    Returns:
        The URL with the given parameters replacing any same-named existing ones
    """
    return add_query_params(remove_query_params(url, params), params)
