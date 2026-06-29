"""Utilities for OAuth 2.0 Resource Indicators (RFC 8707) and PKCE (RFC 7636)."""

import time
from urllib.parse import urlparse, urlsplit, urlunsplit

from pydantic import AnyUrl, HttpUrl


def resource_url_from_server_url(url: str | HttpUrl | AnyUrl) -> str:
    """Convert server URL to canonical resource URL per RFC 8707.

    Lowercases scheme/host and strips the fragment (RFC 8707 section 2: resource URIs
    "MUST NOT include a fragment component").
    """
    url_str = str(url)

    parsed = urlsplit(url_str)
    canonical = urlunsplit(parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower(), fragment=""))

    return canonical


def check_resource_allowed(requested_resource: str, configured_resource: str) -> bool:
    """Check if a requested resource URL matches a configured resource URL.

    Matches when the origin is identical and the requested path starts with the
    configured path, so a token for a parent resource covers child resources.
    """
    requested = urlparse(requested_resource)
    configured = urlparse(configured_resource)

    if requested.scheme.lower() != configured.scheme.lower() or requested.netloc.lower() != configured.netloc.lower():
        return False

    # Normalize trailing slashes so "/foo" == "/foo/" and "/api123/" can't prefix-match "/api/".
    requested_path = requested.path
    configured_path = configured.path
    if not requested_path.endswith("/"):
        requested_path += "/"
    if not configured_path.endswith("/"):
        configured_path += "/"

    return requested_path.startswith(configured_path)


def calculate_token_expiry(expires_in: int | str | None) -> float | None:
    """Calculate the Unix expiry timestamp from `expires_in` seconds, or None if not specified.

    Accepts strings because some servers return `expires_in` as a string.
    """
    if expires_in is None:
        return None  # pragma: no cover
    return time.time() + int(expires_in)
