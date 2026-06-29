"""Tests for OAuth 2.0 Resource Indicators (RFC 8707) utilities."""

from pydantic import HttpUrl

from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url


def test_resource_url_from_server_url_removes_fragment():
    assert resource_url_from_server_url("https://example.com/path#fragment") == "https://example.com/path"
    assert resource_url_from_server_url("https://example.com/#fragment") == "https://example.com/"


def test_resource_url_from_server_url_preserves_path():
    assert (
        resource_url_from_server_url("https://example.com/path/to/resource") == "https://example.com/path/to/resource"
    )
    assert resource_url_from_server_url("https://example.com/") == "https://example.com/"
    assert resource_url_from_server_url("https://example.com") == "https://example.com"


def test_resource_url_from_server_url_preserves_query():
    assert resource_url_from_server_url("https://example.com/path?foo=bar") == "https://example.com/path?foo=bar"
    assert resource_url_from_server_url("https://example.com/?key=value") == "https://example.com/?key=value"


def test_resource_url_from_server_url_preserves_port():
    assert resource_url_from_server_url("https://example.com:8443/path") == "https://example.com:8443/path"
    assert resource_url_from_server_url("http://example.com:8080/") == "http://example.com:8080/"


def test_resource_url_from_server_url_lowercase_scheme_and_host():
    assert resource_url_from_server_url("HTTPS://EXAMPLE.COM/path") == "https://example.com/path"
    assert resource_url_from_server_url("Http://Example.Com:8080/") == "http://example.com:8080/"


def test_resource_url_from_server_url_handles_pydantic_urls():
    url = HttpUrl("https://example.com/path")
    assert resource_url_from_server_url(url) == "https://example.com/path"


def test_check_resource_allowed_identical_urls():
    assert check_resource_allowed("https://example.com/path", "https://example.com/path") is True
    assert check_resource_allowed("https://example.com/", "https://example.com/") is True
    assert check_resource_allowed("https://example.com", "https://example.com") is True


def test_check_resource_allowed_different_schemes():
    assert check_resource_allowed("https://example.com/path", "http://example.com/path") is False
    assert check_resource_allowed("http://example.com/", "https://example.com/") is False


def test_check_resource_allowed_different_domains():
    assert check_resource_allowed("https://example.com/path", "https://example.org/path") is False
    assert check_resource_allowed("https://sub.example.com/", "https://example.com/") is False


def test_check_resource_allowed_different_ports():
    assert check_resource_allowed("https://example.com:8443/path", "https://example.com/path") is False
    assert check_resource_allowed("https://example.com:8080/", "https://example.com:8443/") is False


def test_check_resource_allowed_hierarchical_matching():
    # Parent resource allows child resources
    assert check_resource_allowed("https://example.com/api/v1/users", "https://example.com/api") is True
    assert check_resource_allowed("https://example.com/api/v1", "https://example.com/api") is True
    assert check_resource_allowed("https://example.com/mcp/server", "https://example.com/mcp") is True

    assert check_resource_allowed("https://example.com/api", "https://example.com/api") is True

    # Parent cannot use child's token
    assert check_resource_allowed("https://example.com/api", "https://example.com/api/v1") is False
    assert check_resource_allowed("https://example.com/", "https://example.com/api") is False


def test_check_resource_allowed_path_boundary_matching():
    # A path prefix only matches at a `/` segment boundary
    assert check_resource_allowed("https://example.com/apiextra", "https://example.com/api") is False
    assert check_resource_allowed("https://example.com/api123", "https://example.com/api") is False
    assert check_resource_allowed("https://example.com/api/", "https://example.com/api") is True
    assert check_resource_allowed("https://example.com/api/v1", "https://example.com/api/") is True


def test_check_resource_allowed_trailing_slash_handling():
    assert check_resource_allowed("https://example.com/api/", "https://example.com/api") is True
    assert check_resource_allowed("https://example.com/api", "https://example.com/api/") is True
    assert check_resource_allowed("https://example.com/api/v1", "https://example.com/api") is True
    assert check_resource_allowed("https://example.com/api/v1", "https://example.com/api/") is True


def test_check_resource_allowed_case_insensitive_origin():
    assert check_resource_allowed("https://EXAMPLE.COM/path", "https://example.com/path") is True
    assert check_resource_allowed("HTTPS://example.com/path", "https://example.com/path") is True
    assert check_resource_allowed("https://Example.Com:8080/api", "https://example.com:8080/api") is True


def test_check_resource_allowed_empty_paths():
    assert check_resource_allowed("https://example.com", "https://example.com") is True
    assert check_resource_allowed("https://example.com/", "https://example.com") is True
    assert check_resource_allowed("https://example.com/api", "https://example.com") is True
