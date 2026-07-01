"""Tests for OAuth 2.0 Resource Indicators utilities."""

import time

from pydantic import HttpUrl

from mcp.shared.auth_utils import (
    calculate_token_refresh_time,
    check_resource_allowed,
    resource_url_from_server_url,
)

# Tests for resource_url_from_server_url function


def test_resource_url_from_server_url_removes_fragment():
    """Fragment should be removed per RFC 8707."""
    assert resource_url_from_server_url("https://example.com/path#fragment") == "https://example.com/path"
    assert resource_url_from_server_url("https://example.com/#fragment") == "https://example.com/"


def test_resource_url_from_server_url_preserves_path():
    """Path should be preserved."""
    assert (
        resource_url_from_server_url("https://example.com/path/to/resource") == "https://example.com/path/to/resource"
    )
    assert resource_url_from_server_url("https://example.com/") == "https://example.com/"
    assert resource_url_from_server_url("https://example.com") == "https://example.com"


def test_resource_url_from_server_url_preserves_query():
    """Query parameters should be preserved."""
    assert resource_url_from_server_url("https://example.com/path?foo=bar") == "https://example.com/path?foo=bar"
    assert resource_url_from_server_url("https://example.com/?key=value") == "https://example.com/?key=value"


def test_resource_url_from_server_url_preserves_port():
    """Non-default ports should be preserved."""
    assert resource_url_from_server_url("https://example.com:8443/path") == "https://example.com:8443/path"
    assert resource_url_from_server_url("http://example.com:8080/") == "http://example.com:8080/"


def test_resource_url_from_server_url_lowercase_scheme_and_host():
    """Scheme and host should be lowercase for canonical form."""
    assert resource_url_from_server_url("HTTPS://EXAMPLE.COM/path") == "https://example.com/path"
    assert resource_url_from_server_url("Http://Example.Com:8080/") == "http://example.com:8080/"


def test_resource_url_from_server_url_handles_pydantic_urls():
    """Should handle Pydantic URL types."""
    url = HttpUrl("https://example.com/path")
    assert resource_url_from_server_url(url) == "https://example.com/path"


# Tests for check_resource_allowed function


def test_check_resource_allowed_identical_urls():
    """Identical URLs should match."""
    assert check_resource_allowed("https://example.com/path", "https://example.com/path") is True
    assert check_resource_allowed("https://example.com/", "https://example.com/") is True
    assert check_resource_allowed("https://example.com", "https://example.com") is True


def test_check_resource_allowed_different_schemes():
    """Different schemes should not match."""
    assert check_resource_allowed("https://example.com/path", "http://example.com/path") is False
    assert check_resource_allowed("http://example.com/", "https://example.com/") is False


def test_check_resource_allowed_different_domains():
    """Different domains should not match."""
    assert check_resource_allowed("https://example.com/path", "https://example.org/path") is False
    assert check_resource_allowed("https://sub.example.com/", "https://example.com/") is False


def test_check_resource_allowed_different_ports():
    """Different ports should not match."""
    assert check_resource_allowed("https://example.com:8443/path", "https://example.com/path") is False
    assert check_resource_allowed("https://example.com:8080/", "https://example.com:8443/") is False


def test_check_resource_allowed_hierarchical_matching():
    """Child paths should match parent paths."""
    # Parent resource allows child resources
    assert check_resource_allowed("https://example.com/api/v1/users", "https://example.com/api") is True
    assert check_resource_allowed("https://example.com/api/v1", "https://example.com/api") is True
    assert check_resource_allowed("https://example.com/mcp/server", "https://example.com/mcp") is True

    # Exact match
    assert check_resource_allowed("https://example.com/api", "https://example.com/api") is True

    # Parent cannot use child's token
    assert check_resource_allowed("https://example.com/api", "https://example.com/api/v1") is False
    assert check_resource_allowed("https://example.com/", "https://example.com/api") is False


def test_check_resource_allowed_path_boundary_matching():
    """Path matching should respect boundaries."""
    # Should not match partial path segments
    assert check_resource_allowed("https://example.com/apiextra", "https://example.com/api") is False
    assert check_resource_allowed("https://example.com/api123", "https://example.com/api") is False

    # Should match with trailing slash
    assert check_resource_allowed("https://example.com/api/", "https://example.com/api") is True
    assert check_resource_allowed("https://example.com/api/v1", "https://example.com/api/") is True


def test_check_resource_allowed_trailing_slash_handling():
    """Trailing slashes should be handled correctly."""
    # With and without trailing slashes
    assert check_resource_allowed("https://example.com/api/", "https://example.com/api") is True
    assert check_resource_allowed("https://example.com/api", "https://example.com/api/") is True
    assert check_resource_allowed("https://example.com/api/v1", "https://example.com/api") is True
    assert check_resource_allowed("https://example.com/api/v1", "https://example.com/api/") is True


def test_check_resource_allowed_case_insensitive_origin():
    """Origin comparison should be case-insensitive."""
    assert check_resource_allowed("https://EXAMPLE.COM/path", "https://example.com/path") is True
    assert check_resource_allowed("HTTPS://example.com/path", "https://example.com/path") is True
    assert check_resource_allowed("https://Example.Com:8080/api", "https://example.com:8080/api") is True


def test_check_resource_allowed_empty_paths():
    """Empty paths should be handled correctly."""
    assert check_resource_allowed("https://example.com", "https://example.com") is True
    assert check_resource_allowed("https://example.com/", "https://example.com") is True
    assert check_resource_allowed("https://example.com/api", "https://example.com") is True


# Tests for calculate_token_refresh_time function


def test_calculate_token_refresh_time_none_expires_in():
    """None expires_in means no expiry info -> no refresh schedule."""
    assert calculate_token_refresh_time(None) is None


def test_calculate_token_refresh_time_normal_ttl_within_window():
    """For a normal TTL the refresh point falls inside the expected jitter window
    and strictly before hard expiry."""
    expires_in = 3600
    before = time.time()
    refresh_at = calculate_token_refresh_time(expires_in)
    after = time.time()

    assert refresh_at is not None
    hard_expiry_lower = before + expires_in
    # With default fraction 0.8 and up to 30s of jitter subtracted, the refresh
    # point lies in [now + 0.8*ttl - 30, now + 0.8*ttl].
    assert before + expires_in * 0.8 - 30.0 <= refresh_at <= after + expires_in * 0.8
    # Must be strictly before hard expiry and in the future.
    assert refresh_at < hard_expiry_lower
    assert refresh_at > before


def test_calculate_token_refresh_time_accepts_string_expires_in():
    """expires_in may arrive as a string from some servers."""
    refresh_at = calculate_token_refresh_time("3600", jitter=0.0)
    now = time.time()
    assert refresh_at is not None
    # Roughly now + 0.8 * 3600 = now + 2880 (allow small scheduling slack).
    assert now + 2880 - 5 <= refresh_at <= now + 2880 + 5


def test_calculate_token_refresh_time_injected_jitter_is_deterministic():
    """Injecting jitter makes the function deterministic/testable."""
    expires_in = 1000
    now = time.time()
    refresh_at = calculate_token_refresh_time(expires_in, jitter=10.0)
    # now + 0.8*1000 - 10 = now + 790 (allow small scheduling slack).
    assert now + 790 - 2 <= refresh_at <= now + 790 + 2  # type: ignore[operator]


def test_calculate_token_refresh_time_jitter_pulls_earlier():
    """Larger jitter must produce an earlier (smaller) refresh timestamp."""
    expires_in = 1000
    no_jitter = calculate_token_refresh_time(expires_in, jitter=0.0)
    small_jitter = calculate_token_refresh_time(expires_in, jitter=5.0)
    big_jitter = calculate_token_refresh_time(expires_in, jitter=25.0)

    assert no_jitter is not None and small_jitter is not None and big_jitter is not None
    # Jitter is subtracted, so more jitter -> earlier refresh.
    assert big_jitter < small_jitter < no_jitter


def test_calculate_token_refresh_time_never_past_hard_expiry():
    """The refresh point is always strictly before hard expiry for positive TTLs."""
    for expires_in in (1, 5, 30, 60, 300, 3600, 86400):
        before = time.time()
        refresh_at = calculate_token_refresh_time(expires_in, jitter=0.0)
        assert refresh_at is not None
        assert refresh_at <= before + expires_in
        assert refresh_at >= before  # never in the past


def test_calculate_token_refresh_time_tiny_ttl_no_negative():
    """Very short TTLs (smaller than max jitter) must not go negative or before now."""
    now = time.time()
    # 10s TTL with a requested 30s jitter: jitter must be clamped to the
    # available window (0.8 * 10 = 8s) so the result stays >= now.
    refresh_at = calculate_token_refresh_time(10, max_jitter_seconds=30.0, jitter=30.0)
    assert refresh_at is not None
    assert refresh_at >= now
    assert refresh_at <= now + 10


def test_calculate_token_refresh_time_zero_ttl():
    """A zero TTL collapses to roughly now without going negative."""
    now = time.time()
    refresh_at = calculate_token_refresh_time(0)
    assert refresh_at is not None
    assert now - 1 <= refresh_at <= now + 1


def test_calculate_token_refresh_time_custom_fraction():
    """refresh_fraction controls how far into the lifetime we refresh."""
    expires_in = 1000
    now = time.time()
    refresh_at = calculate_token_refresh_time(expires_in, refresh_fraction=0.5, jitter=0.0)
    assert refresh_at is not None
    # now + 0.5 * 1000 = now + 500 (allow small scheduling slack).
    assert now + 500 - 2 <= refresh_at <= now + 500 + 2
