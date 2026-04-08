"""Tests for OAuth 2.0 shared code."""

import pytest

from mcp.shared.auth import InvalidScopeError, OAuthClientInformationFull, OAuthClientMetadata, OAuthMetadata


def _make_client(scope: str | None) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        redirect_uris=["https://example.com/callback"],
        scope=scope,
        client_id="test-client",
    )


def test_validate_scope_returns_none_when_no_scope_requested():
    client = _make_client("read write")
    assert client.validate_scope(None) is None


def test_validate_scope_allows_registered_scopes():
    client = _make_client("read write")
    assert client.validate_scope("read") == ["read"]
    assert client.validate_scope("read write") == ["read", "write"]


def test_validate_scope_raises_for_unregistered_scope():
    client = _make_client("read")
    with pytest.raises(InvalidScopeError):
        client.validate_scope("read admin")


def test_validate_scope_allows_any_scope_when_client_has_no_scope_restriction():
    """When client.scope is None, any requested scope should be allowed (issue #2216)."""
    client = _make_client(None)
    assert client.validate_scope("read") == ["read"]
    assert client.validate_scope("read write admin") == ["read", "write", "admin"]


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
