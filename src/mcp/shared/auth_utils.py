"""Utilities for OAuth 2.0 Resource Indicators (RFC 8707) and PKCE (RFC 7636)."""

import time
from urllib.parse import urlparse, urlsplit, urlunsplit

from pydantic import AnyUrl, HttpUrl

_DEFAULT_PORTS = {"http": 80, "https": 443}


def resource_url_from_server_url(url: str | HttpUrl | AnyUrl) -> str:
    """Convert server URL to canonical resource URL per RFC 8707.

    RFC 8707 section 2 states that resource URIs "MUST NOT include a fragment component".
    Returns absolute URI with lowercase scheme/host and the scheme's default port
    elided (RFC 3986 §6.2.3) for canonical form.

    Args:
        url: Server URL to convert

    Returns:
        Canonical resource URL string

    Raises:
        ValueError: If the URL's port is non-numeric or out of range. RFC 3986's
            grammar puts no upper bound on port digits, so such URLs can arrive
            from outside; callers passing untrusted input must handle this.
    """
    # Convert to string if needed
    url_str = str(url)

    # Parse the URL and remove fragment, create canonical form
    parsed = urlsplit(url_str)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    # RFC 3986 §6.2.3: an explicit default port is equivalent to omitting it.
    if parsed.port is not None and _DEFAULT_PORTS.get(scheme) == parsed.port:
        userinfo, sep, hostport = netloc.rpartition("@")
        netloc = f"{userinfo}{sep}{hostport.rsplit(':', 1)[0]}"
    return urlunsplit(parsed._replace(scheme=scheme, netloc=netloc, fragment=""))


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


def check_token_audience(token_resource: str, server_resource: str | HttpUrl | AnyUrl) -> bool:
    """Return True iff a token's RFC 8707 resource indicator identifies this server.

    Server-side audience validation is canonical-URI equality (authorization.mdx
    Token Audience Binding): a token for a parent or sibling path on the same
    origin is NOT for this server. Contrast check_resource_allowed, which is the
    client-side hierarchical question and intentionally more permissive.
    """
    try:
        token_canonical = resource_url_from_server_url(token_resource)
    except ValueError:
        # An audience we cannot canonicalize does not identify this server. The
        # server side stays unwrapped: it is AnyHttpUrl-validated at config time,
        # and a garbage own-config URL should fail loudly, not silently 401.
        return False
    # The rstrip is deliberate trailing-slash tolerance, not 3986 equivalence:
    # authorization.mdx's canonical-URI note expects both spellings of one resource
    # to circulate (recommending the slashless form for interop), and pydantic's
    # AnyHttpUrl forces a root slash (str(AnyHttpUrl("https://h")) == "https://h/")
    # while the spec's own example token request sends resource=https://h — without
    # this, every root-path deployment would 401 spec-conformant clients.
    return token_canonical.rstrip("/") == resource_url_from_server_url(server_resource).rstrip("/")


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
