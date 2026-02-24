import pytest
from pydantic import AnyHttpUrl

from mcp.server.auth.routes import validate_issuer_url


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
