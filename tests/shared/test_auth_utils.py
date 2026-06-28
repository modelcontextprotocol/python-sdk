"""Tests for OAuth 2.0 Resource Indicators utilities."""

import pytest
from pydantic import HttpUrl

from mcp.shared.auth_utils import check_resource_allowed, check_token_audience, resource_url_from_server_url

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


def test_resource_url_from_server_url_strips_default_port():
    """An explicit default port is equivalent to omitting it (RFC 3986 §6.2.3)."""
    assert resource_url_from_server_url("https://example.com:443/mcp") == "https://example.com/mcp"
    assert resource_url_from_server_url("http://example.com:80/mcp") == "http://example.com/mcp"
    # Only the scheme's own default is stripped — :80 on https is significant.
    assert resource_url_from_server_url("https://example.com:80/mcp") == "https://example.com:80/mcp"
    # IPv6 brackets survive the rewrite.
    assert resource_url_from_server_url("https://[::1]:443/mcp") == "https://[::1]/mcp"


def test_check_token_audience_ignores_default_port():
    """A token issued for `https://h:443/mcp` is for the server at `https://h/mcp`."""
    assert check_token_audience("https://h:443/mcp", "https://h/mcp") is True
    assert check_token_audience("https://h/mcp", "https://h:443/mcp") is True
    assert check_token_audience("https://h:8443/mcp", "https://h/mcp") is False


def test_check_token_audience_treats_an_unparseable_audience_as_a_mismatch():
    """A token audience whose port cannot be parsed does not identify this server.

    SDK-defined: RFC 3986's grammar puts no upper bound on port digits, so an AS can
    legitimately issue a token for `https://h:99999/mcp`; urllib refuses to parse such
    ports, and that canonicalization failure must read as a mismatch, not an error.
    """
    assert check_token_audience("https://h:99999/mcp", "https://h/mcp") is False
    assert check_token_audience("https://h:abc/mcp", "https://h/mcp") is False


def test_check_token_audience_treats_trailing_slash_variants_as_one_resource():
    """`https://h/api/` and `https://h/api` are the same audience, in either direction.

    SDK-defined interop tolerance per authorization.mdx's canonical-URI note (both
    spellings of one resource circulate; the slashless form is merely recommended), and
    required at root because pydantic's `AnyHttpUrl` renders `https://h` as `https://h/`
    while the spec's example token request sends the slashless form.
    """
    assert check_token_audience("https://h/api/", "https://h/api") is True
    assert check_token_audience("https://h/api", "https://h/api/") is True
    assert check_token_audience("https://h", "https://h/") is True


def test_check_token_audience_rejects_sibling_and_child_paths():
    """Trailing-slash tolerance does not loosen path equality: siblings and children mismatch."""
    assert check_token_audience("https://h/api123", "https://h/api") is False
    assert check_token_audience("https://h/api/sub", "https://h/api") is False


def test_resource_url_from_server_url_lowercase_scheme_and_host():
    """Scheme and host should be lowercase for canonical form."""
    assert resource_url_from_server_url("HTTPS://EXAMPLE.COM/path") == "https://example.com/path"
    assert resource_url_from_server_url("Http://Example.Com:8080/") == "http://example.com:8080/"


def test_resource_url_from_server_url_handles_pydantic_urls():
    """Should handle Pydantic URL types."""
    url = HttpUrl("https://example.com/path")
    assert resource_url_from_server_url(url) == "https://example.com/path"


def test_resource_url_from_server_url_raises_on_unparseable_port():
    """An out-of-range or non-numeric port raises ValueError, as documented.

    SDK-defined: the canonicalizer stays strict for its trusted own-config callers;
    `check_token_audience` wraps the untrusted token side. The message is urllib's,
    so only the exception type is pinned.
    """
    with pytest.raises(ValueError):
        resource_url_from_server_url("https://example.com:99999/mcp")
    with pytest.raises(ValueError):
        resource_url_from_server_url("https://example.com:abc/mcp")


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
