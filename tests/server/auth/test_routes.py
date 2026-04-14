import pytest
from pydantic import AnyHttpUrl

from mcp.server.auth.routes import create_auth_routes, validate_issuer_url
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from tests.server.mcpserver.auth.test_auth_integration import MockOAuthProvider


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


def test_create_auth_routes_default_paths():
    """Auth routes are registered at root when issuer_url has no path."""
    provider = MockOAuthProvider()
    routes = create_auth_routes(
        provider,
        issuer_url=AnyHttpUrl("https://example.com"),
        client_registration_options=ClientRegistrationOptions(enabled=True),
        revocation_options=RevocationOptions(enabled=True),
    )
    paths = [route.path for route in routes]
    assert "/.well-known/oauth-authorization-server" in paths
    assert "/authorize" in paths
    assert "/token" in paths
    assert "/register" in paths
    assert "/revoke" in paths


def test_create_auth_routes_custom_base_path():
    """Auth routes are prefixed with the issuer_url path for gateway deployments."""
    provider = MockOAuthProvider()
    routes = create_auth_routes(
        provider,
        issuer_url=AnyHttpUrl("https://example.com/custom/path"),
        client_registration_options=ClientRegistrationOptions(enabled=True),
        revocation_options=RevocationOptions(enabled=True),
    )
    paths = [route.path for route in routes]
    assert "/custom/path/.well-known/oauth-authorization-server" in paths
    assert "/custom/path/authorize" in paths
    assert "/custom/path/token" in paths
    assert "/custom/path/register" in paths
    assert "/custom/path/revoke" in paths


def test_create_auth_routes_trailing_slash_stripped():
    """Trailing slash on issuer_url path is stripped to avoid double slashes."""
    provider = MockOAuthProvider()
    routes = create_auth_routes(
        provider,
        issuer_url=AnyHttpUrl("https://example.com/base/"),
        client_registration_options=ClientRegistrationOptions(enabled=True),
        revocation_options=RevocationOptions(enabled=True),
    )
    paths = [route.path for route in routes]
    assert "/base/.well-known/oauth-authorization-server" in paths
    assert "/base/authorize" in paths
    assert "/base/token" in paths
