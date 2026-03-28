"""Tests for OAuth 2.0 shared code."""

import pytest
from pydantic import AnyUrl

from mcp.shared.auth import InvalidScopeError, OAuthClientMetadata, OAuthMetadata


def test_oauth():
    """Should not throw when parsing OAuth metadata."""
    OAuthMetadata.model_validate(
        {
            "issuer": "https://example.com",
            "authorization_endpoint": "https://example.com/oauth2/authorize",
            "token_endpoint": "https://example.com/oauth2/token",
            "scopes_supported": ["read", "write"],
            "response_types_supported": ["code", "token"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        }
    )


def test_oidc():
    """Should not throw when parsing OIDC metadata."""
    OAuthMetadata.model_validate(
        {
            "issuer": "https://example.com",
            "authorization_endpoint": "https://example.com/oauth2/authorize",
            "token_endpoint": "https://example.com/oauth2/token",
            "end_session_endpoint": "https://example.com/logout",
            "id_token_signing_alg_values_supported": ["RS256"],
            "jwks_uri": "https://example.com/.well-known/jwks.json",
            "response_types_supported": ["code", "token"],
            "revocation_endpoint": "https://example.com/oauth2/revoke",
            "scopes_supported": ["openid", "read", "write"],
            "subject_types_supported": ["public"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
            "userinfo_endpoint": "https://example.com/oauth2/userInfo",
        }
    )


def test_oauth_with_jarm():
    """Should not throw when parsing OAuth metadata that includes JARM response modes."""
    OAuthMetadata.model_validate(
        {
            "issuer": "https://example.com",
            "authorization_endpoint": "https://example.com/oauth2/authorize",
            "token_endpoint": "https://example.com/oauth2/token",
            "scopes_supported": ["read", "write"],
            "response_types_supported": ["code", "token"],
            "response_modes_supported": [
                "query",
                "fragment",
                "form_post",
                "query.jwt",
                "fragment.jwt",
                "form_post.jwt",
                "jwt",
            ],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        }
    )


def test_validate_scope_none_required_scopes_accepts_all():
    """When client has no scope restrictions (scope=None), all requested scopes should be accepted."""
    client = OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        scope=None,
    )
    result = client.validate_scope("read write admin")
    assert result == ["read", "write", "admin"]


def test_validate_scope_none_requested_scope_returns_none():
    """When no scope is requested, validate_scope should return None."""
    client = OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        scope="read write",
    )
    result = client.validate_scope(None)
    assert result is None


def test_validate_scope_rejects_unauthorized_scope():
    """When client has specific allowed scopes, unauthorized scopes should be rejected."""
    client = OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        scope="read",
    )
    with pytest.raises(InvalidScopeError, match="write"):
        client.validate_scope("read write")


def test_validate_scope_accepts_authorized_scope():
    """When client has specific allowed scopes, authorized scopes should be accepted."""
    client = OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        scope="read write",
    )
    result = client.validate_scope("read write")
    assert result == ["read", "write"]
