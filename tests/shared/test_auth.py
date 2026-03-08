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


class TestValidateScope:
    """Tests for OAuthClientMetadata.validate_scope()."""

    def _make_client(self, scope=None):
        return OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
            scope=scope,
        )

    def test_requested_none_returns_none(self):
        """When no scope is requested, validate_scope returns None."""
        client = self._make_client(scope="read write")
        assert client.validate_scope(None) is None

    def test_client_scope_none_allows_any_requested_scopes(self):
        """When client has no scope restrictions (None), any requested scopes are allowed.

        Regression test for #2216: validate_scope treated None as empty list,
        rejecting all scopes with InvalidScopeError.
        """
        client = self._make_client(scope=None)
        result = client.validate_scope("read write admin")
        assert result == ["read", "write", "admin"]

    def test_client_scope_none_allows_single_scope(self):
        """When client has no scope restrictions, a single requested scope is allowed."""
        client = self._make_client(scope=None)
        result = client.validate_scope("read")
        assert result == ["read"]

    def test_allowed_scopes_accepted(self):
        """Requested scopes that are a subset of client scopes are accepted."""
        client = self._make_client(scope="read write admin")
        result = client.validate_scope("read write")
        assert result == ["read", "write"]

    def test_disallowed_scope_raises(self):
        """Requesting a scope not in the client's registered scopes raises InvalidScopeError."""
        client = self._make_client(scope="read write")
        with pytest.raises(InvalidScopeError, match="admin"):
            client.validate_scope("read admin")

    def test_all_scopes_match(self):
        """Requesting exactly the registered scopes works."""
        client = self._make_client(scope="read write")
        result = client.validate_scope("read write")
        assert result == ["read", "write"]
