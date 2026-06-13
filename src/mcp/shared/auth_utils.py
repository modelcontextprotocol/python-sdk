"""Utilities for OAuth 2.0 Resource Indicators (RFC 8707) and PKCE (RFC 7636)."""

import random
import time
from urllib.parse import urlparse, urlsplit, urlunsplit

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


def calculate_token_refresh_time(
    expires_in: int | str | None,
    *,
    refresh_fraction: float = 0.8,
    max_jitter_seconds: float = 30.0,
    jitter: float | None = None,
) -> float | None:
    """Calculate when a token should be *proactively* refreshed.

    Reactive refresh (waiting until a token has already expired) means that, for a
    fleet of OAuth-backed MCP connectors provisioned around the same time, every
    token tends to expire inside the same narrow window. When they do, all of those
    clients try to refresh simultaneously, producing a "thundering herd" of refresh
    requests against the authorization server -- contention, rate limiting, and
    spurious auth failures.

    To avoid that, this returns a timestamp *before* hard expiry at which the token
    should be refreshed:

        refresh_at = now + expires_in * refresh_fraction - jitter

    The jitter is always *subtracted* so it pulls the refresh point earlier and can
    never push it past the hard-expiry boundary. Spreading each client's refresh
    point by a small random amount means a fleet naturally desynchronizes instead of
    refreshing in lockstep.

    Args:
        expires_in: Seconds until token expiration (may be a string from some servers).
        refresh_fraction: Fraction of the token lifetime after which to refresh.
            Defaults to 0.8 (refresh once 80% of the lifetime has elapsed).
        max_jitter_seconds: Upper bound (in seconds) of the random jitter subtracted
            from the refresh point. Defaults to 30s.
        jitter: Optional explicit jitter value (seconds). When provided it is used
            directly instead of drawing a random value, which keeps the function
            deterministic and testable. When None, a value in
            ``[0, max_jitter_seconds]`` is drawn at random.

    Returns:
        Unix timestamp at which the token should be proactively refreshed, or None
        if ``expires_in`` is None (no expiry information -> nothing to schedule).
        The result is always in ``(now, hard_expiry]`` and never in the past.
    """
    if expires_in is None:
        return None

    expires_in_seconds = int(expires_in)
    now = time.time()
    hard_expiry = now + expires_in_seconds

    # Base proactive point: refresh once `refresh_fraction` of the lifetime elapsed.
    refresh_at = now + expires_in_seconds * refresh_fraction

    # Cap the jitter so it can never reach back before `now`, which matters for very
    # short TTLs (e.g. expires_in smaller than max_jitter_seconds). The window we are
    # allowed to pull earlier into is (refresh_at - now); never jitter more than that.
    available_window = refresh_at - now
    effective_max_jitter = min(max_jitter_seconds, max(available_window, 0.0))

    if jitter is None:
        applied_jitter = random.uniform(0, effective_max_jitter)
    else:
        # Clamp an injected jitter into the valid range to preserve invariants.
        applied_jitter = min(max(jitter, 0.0), effective_max_jitter)

    refresh_at -= applied_jitter

    # Final guard: keep the result strictly within (now, hard_expiry]. For tiny or
    # zero TTLs this collapses gracefully toward `now` rather than going negative or
    # past the hard-expiry boundary.
    if refresh_at < now:
        refresh_at = now
    if refresh_at > hard_expiry:
        refresh_at = hard_expiry

    return refresh_at
