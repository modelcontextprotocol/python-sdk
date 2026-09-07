"""Tests for OAuth 2.0 Resource Indicators utilities."""

import itertools

import pytest
from pydantic import AnyHttpUrl, HttpUrl

from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url

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


@pytest.mark.parametrize(
    ("server_url", "expected"),
    [
        ("https://example.com/api/../admin", "https://example.com/admin"),
        ("https://example.com/api/%2E%2e/admin", "https://example.com/admin"),
        ("https://example.com/api/.%2e/admin", "https://example.com/admin"),
        ("https://example.com/api/./v1", "https://example.com/api/v1"),
        ("https://example.com/api/v1/..", "https://example.com/api/"),
        ("https://example.com/api/v1/.", "https://example.com/api/v1/"),
        ("https://example.com/../admin", "https://example.com/admin"),
        ("https://example.com/a//b", "https://example.com/a//b"),
        ("https://example.com/a%2Fb/c", "https://example.com/a%2Fb/c"),
    ],
)
def test_resource_url_from_server_url_resolves_dot_segments(server_url: str, expected: str):
    """Dot-segments (including `%2E` spellings) are resolved per RFC 3986 section 5.2.4.

    Empty segments and encoded slashes are not path separators and stay as written.
    """
    assert resource_url_from_server_url(server_url) == expected


def test_resource_url_from_server_url_path_matches_whatwg_resolution_for_literal_dot_segments():
    """Every combination of literal `.`, `..`, empty and plain segments resolves as pydantic's WHATWG parser does.

    The PRM `resource` side is parsed by `AnyHttpUrl`, so both operands of `check_resource_allowed`
    must agree on dot-segment resolution for the comparison to be meaningful.
    """
    atoms = ["", ".", "..", "a", "b.", "..."]
    for count in range(1, 5):
        for segments in itertools.product(atoms, repeat=count):
            path = "/" + "/".join(segments)
            expected = AnyHttpUrl(f"https://example.com{path}").path
            assert resource_url_from_server_url(f"https://example.com{path}") == f"https://example.com{expected}"


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


@pytest.mark.parametrize(
    "requested",
    [
        "https://example.com/api/../admin",
        "https://example.com/api/%2e%2e/admin",
        "https://example.com/api/v1/../../admin",
        "https://example.com/api/..",
    ],
)
def test_check_resource_allowed_rejects_dot_segments_escaping_configured_path(requested: str):
    """A requested path that resolves outside the configured path is not a hierarchical match."""
    assert check_resource_allowed(requested, "https://example.com/api") is False


def test_check_resource_allowed_resolves_dot_segments_on_both_sides():
    """Both URLs are compared in resolved form, so equivalent spellings agree (SDK-defined matching)."""
    assert check_resource_allowed("https://example.com/api/./v1", "https://example.com/api") is True
    assert check_resource_allowed("https://example.com/api/v1", "https://example.com/other/../api") is True
    assert check_resource_allowed("https://example.com/api/v1", "https://example.com/api/v1/../v2") is False


def test_check_resource_allowed_keeps_encoded_slash_and_params_in_segment():
    """`%2F` and `;params` are part of a segment (RFC 3986 sections 2.2, 3.3), not a boundary."""
    assert check_resource_allowed("https://example.com/api%2Fv1", "https://example.com/api") is False
    assert check_resource_allowed("https://example.com/api/v1", "https://example.com/api;x") is False
