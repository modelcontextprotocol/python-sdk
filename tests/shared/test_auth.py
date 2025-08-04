"""Tests for OAuth 2.0 shared code."""
import pytest
from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata


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

class TestProtectedResourceMetadataInvalid:
    """Tests for ProtectedResourceMetadata parsing."""

    def test_invalid_metadata(self):
        """Should throw when parsing invalid metadata."""
        with pytest.raises(ValueError):
            ProtectedResourceMetadata.model_validate(
                {
                    "resource": "Not a valid URL",
                    "authorization_servers": ["https://example.com/oauth2/authorize"],
                    "scopes_supported": ["read", "write"],
                    "bearer_methods_supported": ["header"],
                }
            )

    def test_valid_metadata(self):
        """Should not throw when parsing protected resource metadata."""

        ProtectedResourceMetadata.model_validate(
            {
                "resource": "https://example.com/resource",
                "authorization_servers": ["https://example.com/oauth2/authorize"],
                "scopes_supported": ["read", "write"],
                "bearer_methods_supported": ["header"],
            }
        )

    def test_valid_with_resource_metadata(self):
        """Should not throw when parsing metadata with resource_name and resource_documentation."""

        ProtectedResourceMetadata.model_validate(
            {
                "resource": "https://example.com/resource",
                "authorization_servers": ["https://example.com/oauth2/authorize"],
                "scopes_supported": ["read", "write"],
                "bearer_methods_supported": ["header"],
                "resource_name": "Example Resource",
                "resource_documentation": "https://example.com/resource/documentation",
            }
        )

    def test_valid_witn_invalid_resource_documentation(self):
        """Should throw when parsing metadata with resource_name and resource_documentation."""
        with pytest.raises(ValueError):
            ProtectedResourceMetadata.model_validate(
                {
                    "resource": "https://example.com/resource",
                    "authorization_servers": ["https://example.com/oauth2/authorize"],
                    "scopes_supported": ["read", "write"],
                    "bearer_methods_supported": ["header"],
                    "resource_name": "Example Resource",
                    "resource_documentation": "Not a valid URL",
                }
            )

    def test_valid_full_protected_resource_metadata(self):
        """Should not throw when parsing full metadata."""

        ProtectedResourceMetadata.model_validate(
            {
                "resource": "https://example.com/resource",
                "authorization_servers": ["https://example.com/oauth2/authorize"],
                "jwks_uri": "https://example.com/.well-known/jwks.json",
                "scopes_supported": ["read", "write"],
                "bearer_methods_supported": ["header"],
                "resource_signing_alg_values_supported": ["RS256"],
                "resource_name": "Example Resource",
                "resource_documentation": "https://example.com/resource/documentation",
                "resource_policy_uri": "https://example.com/resource/policy",
                "resource_tos_uri": "https://example.com/resource/tos",
                "tls_client_certificate_bound_access_tokens": True,
                # authorization_details_types_supported is a complext type
                # so we use an empty list for simplicity
                # see RFC9396
                "authorization_details_types_supported": [],
                "dpop_signing_alg_values_supported": ["RS256", "ES256"],
                "dpop_signing_access_tokens": True,
            }
        )
