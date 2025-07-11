"""Tests for OAuth 2.0 shared code."""

from mcp.shared.auth import OAuthMetadata


class TestOAuthMetadata:
    """Tests for OAuthMetadata parsing."""

    def test_oauth(self):
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

    def test_oidc(self):
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
