"""Test for validate_scope fix when self.scope is None"""
import pytest
from mcp.shared.auth import ClientRegistration, InvalidScopeError


def test_validate_scope_with_none_scope_allows_all():
    """When client has no scope restriction (None), all requested scopes should be allowed."""
    client = ClientRegistration(
        client_id="test-client",
        client_secret="secret",
        scope=None,  # No scope restriction
        redirect_uris=["http://localhost/callback"],
    )
    
    # Should not raise - all scopes allowed when no restriction
    result = client.validate_scope("read write admin")
    assert result == ["read", "write", "admin"]


def test_validate_scope_with_empty_requested_returns_none():
    """When requested_scope is None, return None."""
    client = ClientRegistration(
        client_id="test-client",
        client_secret="secret",
        scope="read write",
        redirect_uris=["http://localhost/callback"],
    )
    
    result = client.validate_scope(None)
    assert result is None


def test_validate_scope_with_restrictions_enforced():
    """When client has scope restrictions, only allowed scopes pass."""
    client = ClientRegistration(
        client_id="test-client",
        client_secret="secret",
        scope="read write",
        redirect_uris=["http://localhost/callback"],
    )
    
    # Allowed scope
    result = client.validate_scope("read")
    assert result == ["read"]
    
    # Disallowed scope should raise
    with pytest.raises(InvalidScopeError):
        client.validate_scope("admin")
