"""Tests for RFC 8252 Section 7.3 compliant redirect_uri validation.

RFC 8252 Section 7.3 states:
"The authorization server MUST allow any port to be specified at the time of
the request for loopback IP redirect URIs, to accommodate clients that obtain
an available ephemeral port from the operating system at the time of the request."
"""

import pytest
from pydantic import AnyUrl

from mcp.shared.auth import InvalidRedirectUriError, OAuthClientMetadata


def test_exact_match_non_loopback():
    """Non-loopback URIs must match exactly."""
    client = OAuthClientMetadata(
        redirect_uris=[AnyUrl("https://example.com:8080/callback")]
    )
    
    # Exact match should work
    result = client.validate_redirect_uri(AnyUrl("https://example.com:8080/callback"))
    assert str(result) == "https://example.com:8080/callback"
    
    # Different port should fail
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("https://example.com:9090/callback"))


def test_loopback_localhost_port_ignored():
    """Localhost loopback URIs should ignore port per RFC 8252."""
    client = OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://localhost:8080/callback")]
    )
    
    # Different port should work for loopback
    result = client.validate_redirect_uri(AnyUrl("http://localhost:9999/callback"))
    assert str(result) == "http://localhost:9999/callback"
    
    # Same port should also work
    result = client.validate_redirect_uri(AnyUrl("http://localhost:8080/callback"))
    assert str(result) == "http://localhost:8080/callback"


def test_loopback_ipv4_port_ignored():
    """127.0.0.1 loopback URIs should ignore port per RFC 8252."""
    client = OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://127.0.0.1:5000/")]
    )
    
    # Different port should work for loopback
    result = client.validate_redirect_uri(AnyUrl("http://127.0.0.1:60847/"))
    assert str(result) == "http://127.0.0.1:60847/"


def test_loopback_ipv6_port_ignored():
    """[::1] loopback URIs should ignore port per RFC 8252."""
    client = OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://[::1]:8080/")]
    )
    
    # Different port should work for loopback
    result = client.validate_redirect_uri(AnyUrl("http://[::1]:9999/"))
    assert str(result) == "http://[::1]:9999/"


def test_loopback_scheme_must_match():
    """Loopback URIs must still match scheme."""
    client = OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://localhost:8080/callback")]
    )
    
    # HTTPS vs HTTP should fail
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("https://localhost:9999/callback"))


def test_loopback_path_must_match():
    """Loopback URIs must still match path."""
    client = OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://localhost:8080/callback")]
    )
    
    # Different path should fail
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("http://localhost:9999/other"))


def test_loopback_hostname_must_match():
    """Loopback hostname must match (can't mix localhost and 127.0.0.1)."""
    client = OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://localhost:8080/callback")]
    )
    
    # Different loopback hostname should fail
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("http://127.0.0.1:9999/callback"))


def test_multiple_redirect_uris_loopback():
    """Should match against any registered loopback URI."""
    client = OAuthClientMetadata(
        redirect_uris=[
            AnyUrl("http://localhost:8080/callback"),
            AnyUrl("http://127.0.0.1:5000/auth"),
        ]
    )
    
    # Should match first with different port
    result = client.validate_redirect_uri(AnyUrl("http://localhost:9999/callback"))
    assert str(result) == "http://localhost:9999/callback"
    
    # Should match second with different port
    result = client.validate_redirect_uri(AnyUrl("http://127.0.0.1:6000/auth"))
    assert str(result) == "http://127.0.0.1:6000/auth"


def test_mixed_loopback_and_non_loopback():
    """Client can have both loopback and non-loopback URIs."""
    client = OAuthClientMetadata(
        redirect_uris=[
            AnyUrl("http://localhost:8080/callback"),
            AnyUrl("https://example.com:8080/callback"),
        ]
    )
    
    # Loopback with different port should work
    result = client.validate_redirect_uri(AnyUrl("http://localhost:9999/callback"))
    assert str(result) == "http://localhost:9999/callback"
    
    # Non-loopback with different port should fail
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("https://example.com:9999/callback"))
    
    # Non-loopback exact match should work
    result = client.validate_redirect_uri(AnyUrl("https://example.com:8080/callback"))
    assert str(result) == "https://example.com:8080/callback"


def test_no_redirect_uris_registered():
    """Should fail if no redirect URIs are registered."""
    client = OAuthClientMetadata(redirect_uris=None)
    
    with pytest.raises(InvalidRedirectUriError, match="No redirect URIs registered"):
        client.validate_redirect_uri(AnyUrl("http://localhost:8080/"))


def test_single_registered_uri_omit_request():
    """If only one URI registered and none provided, use the registered one."""
    client = OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://localhost:8080/callback")]
    )
    
    result = client.validate_redirect_uri(None)
    assert str(result) == "http://localhost:8080/callback"


def test_multiple_registered_uris_omit_request():
    """Must specify redirect_uri when multiple are registered."""
    client = OAuthClientMetadata(
        redirect_uris=[
            AnyUrl("http://localhost:8080/callback"),
            AnyUrl("http://127.0.0.1:5000/auth"),
        ]
    )
    
    with pytest.raises(InvalidRedirectUriError, match="must be specified"):
        client.validate_redirect_uri(None)


def test_root_path_normalization():
    """Empty path should be treated as '/'."""
    client = OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://localhost:8080/")]
    )
    
    # Both should match
    result = client.validate_redirect_uri(AnyUrl("http://localhost:9999/"))
    assert str(result) == "http://localhost:9999/"
    
    # Without trailing slash - Pydantic normalizes to include slash
    result = client.validate_redirect_uri(AnyUrl("http://localhost:9999"))
    # AnyUrl normalizes URLs, so both forms match
    assert "localhost:9999" in str(result)
