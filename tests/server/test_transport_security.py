"""Tests for transport security (DNS rebinding protection)."""

from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings


def test_hostname_from_host_ipv6_with_port():
    """_hostname_from_host strips port from [::1]:port (coverage for lines 52-55)."""
    m = TransportSecurityMiddleware(TransportSecuritySettings(enable_dns_rebinding_protection=False))
    assert m._hostname_from_host("[::1]:8080") == "[::1]"


def test_hostname_from_host_ipv6_no_port():
    """_hostname_from_host returns [::1] as-is when no port (coverage for line 56)."""
    m = TransportSecurityMiddleware(TransportSecuritySettings(enable_dns_rebinding_protection=False))
    assert m._hostname_from_host("[::1]") == "[::1]"


def test_hostname_from_host_plain_with_port():
    """_hostname_from_host strips port from hostname (coverage for line 57)."""
    m = TransportSecurityMiddleware(TransportSecuritySettings(enable_dns_rebinding_protection=False))
    assert m._hostname_from_host("app.mysite.com:8080") == "app.mysite.com"
