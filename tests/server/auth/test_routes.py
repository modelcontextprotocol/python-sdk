import pytest
from pydantic import AnyHttpUrl

from mcp.server.auth.routes import build_metadata, validate_issuer_url
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions


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


def test_auth_settings_preserves_path_less_issuer():
    """A path-less issuer passed as a string keeps its canonical form (no trailing slash)."""
    settings = AuthSettings(
        issuer_url="https://as.example.com",  # type: ignore[arg-type]
        resource_server_url="https://rs.example.com",  # type: ignore[arg-type]
    )
    assert str(settings.issuer_url) == "https://as.example.com"
    assert str(settings.resource_server_url) == "https://rs.example.com"


def test_build_metadata_serves_issuer_without_trailing_slash():
    """The served issuer matches the configured one exactly (RFC 8414/9207 string comparison)."""
    settings = AuthSettings(
        issuer_url="https://as.example.com",  # type: ignore[arg-type]
        resource_server_url="https://rs.example.com",  # type: ignore[arg-type]
    )
    metadata = build_metadata(settings.issuer_url, None, ClientRegistrationOptions(), RevocationOptions())

    served = metadata.model_dump(mode="json", exclude_none=True)
    assert served["issuer"] == "https://as.example.com"
    assert served["authorization_endpoint"] == "https://as.example.com/authorize"
    assert served["token_endpoint"] == "https://as.example.com/token"
