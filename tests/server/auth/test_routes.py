import pytest
from pydantic import AnyHttpUrl, AnyUrl

from mcp.server.auth.routes import validate_issuer_url, validate_registered_redirect_uri
from mcp.shared.auth import InvalidRedirectUriError


def test_validate_issuer_url_https_allowed():
    validate_issuer_url(AnyHttpUrl("https://example.com/path"))


def test_validate_issuer_url_http_localhost_allowed():
    validate_issuer_url(AnyHttpUrl("http://localhost:8080/path"))


def test_validate_issuer_url_http_127_0_0_1_allowed():
    validate_issuer_url(AnyHttpUrl("http://127.0.0.1:8080/path"))


def test_validate_issuer_url_http_ipv6_loopback_allowed():
    validate_issuer_url(AnyHttpUrl("http://[::1]:8080/path"))


def test_validate_issuer_url_http_non_loopback_rejected():
    with pytest.raises(ValueError, match="Issuer URL must be HTTPS"):
        validate_issuer_url(AnyHttpUrl("http://evil.com/path"))


def test_validate_issuer_url_http_127_prefix_domain_rejected():
    """A domain like 127.0.0.1.evil.com is not loopback."""
    with pytest.raises(ValueError, match="Issuer URL must be HTTPS"):
        validate_issuer_url(AnyHttpUrl("http://127.0.0.1.evil.com/path"))


def test_validate_issuer_url_http_127_prefix_subdomain_rejected():
    """A domain like 127.0.0.1something.example.com is not loopback."""
    with pytest.raises(ValueError, match="Issuer URL must be HTTPS"):
        validate_issuer_url(AnyHttpUrl("http://127.0.0.1something.example.com/path"))


def test_validate_issuer_url_fragment_rejected():
    with pytest.raises(ValueError, match="fragment"):
        validate_issuer_url(AnyHttpUrl("https://example.com/path#frag"))


def test_validate_issuer_url_query_rejected():
    with pytest.raises(ValueError, match="query"):
        validate_issuer_url(AnyHttpUrl("https://example.com/path?q=1"))


def test_validate_registered_redirect_uri_https_allowed():
    validate_registered_redirect_uri(AnyUrl("https://example.com/cb"))


def test_validate_registered_redirect_uri_https_with_query_allowed():
    validate_registered_redirect_uri(AnyUrl("https://example.com/cb?foo=bar"))


def test_validate_registered_redirect_uri_http_localhost_allowed():
    validate_registered_redirect_uri(AnyUrl("http://localhost:8080/cb"))


def test_validate_registered_redirect_uri_http_127_0_0_1_allowed():
    validate_registered_redirect_uri(AnyUrl("http://127.0.0.1:8080/cb"))


def test_validate_registered_redirect_uri_http_ipv6_loopback_allowed():
    validate_registered_redirect_uri(AnyUrl("http://[::1]:8080/cb"))


def test_validate_registered_redirect_uri_javascript_scheme_rejected():
    with pytest.raises(InvalidRedirectUriError, match="must use https"):
        validate_registered_redirect_uri(AnyUrl("javascript:alert(1)"))


def test_validate_registered_redirect_uri_data_scheme_rejected():
    with pytest.raises(InvalidRedirectUriError, match="must use https"):
        validate_registered_redirect_uri(AnyUrl("data:text/html,x"))


def test_validate_registered_redirect_uri_file_scheme_rejected():
    with pytest.raises(InvalidRedirectUriError, match="must use https"):
        validate_registered_redirect_uri(AnyUrl("file:///etc/passwd"))


def test_validate_registered_redirect_uri_ftp_scheme_rejected():
    with pytest.raises(InvalidRedirectUriError, match="must use https"):
        validate_registered_redirect_uri(AnyUrl("ftp://attacker.example/cb"))


def test_validate_registered_redirect_uri_http_non_loopback_rejected():
    with pytest.raises(InvalidRedirectUriError, match="must use https for non-loopback"):
        validate_registered_redirect_uri(AnyUrl("http://attacker.example/cb"))


def test_validate_registered_redirect_uri_http_127_prefix_domain_rejected():
    """A domain like 127.0.0.1.evil.com is NOT loopback."""
    with pytest.raises(InvalidRedirectUriError, match="must use https for non-loopback"):
        validate_registered_redirect_uri(AnyUrl("http://127.0.0.1.evil.com/cb"))


def test_validate_registered_redirect_uri_fragment_rejected():
    with pytest.raises(InvalidRedirectUriError, match="must not have a fragment"):
        validate_registered_redirect_uri(AnyUrl("https://example.com/cb#frag"))
