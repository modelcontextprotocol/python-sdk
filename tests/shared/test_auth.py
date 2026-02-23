"""Tests for OAuth 2.0 shared code."""

import json

from pydantic import AnyHttpUrl

from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata


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


class TestIssuerTrailingSlash:
    """Tests for issue #1919: trailing slash in issuer URL.

    RFC 8414 examples show issuer URLs without trailing slashes, and some
    OAuth clients require exact match between discovery URL and returned issuer.
    Pydantic's AnyHttpUrl automatically adds a trailing slash, so we strip it
    during serialization.
    """

    def test_oauth_metadata_issuer_no_trailing_slash_in_json(self):
        """Serialized issuer should not have trailing slash."""
        metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://example.com"),
            authorization_endpoint=AnyHttpUrl("https://example.com/oauth2/authorize"),
            token_endpoint=AnyHttpUrl("https://example.com/oauth2/token"),
        )
        serialized = json.loads(metadata.model_dump_json())
        assert serialized["issuer"] == "https://example.com"
        assert not serialized["issuer"].endswith("/")

    def test_oauth_metadata_issuer_with_path_preserves_path(self):
        """Issuer with path should preserve the path, only strip trailing slash."""
        metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://example.com/auth"),
            authorization_endpoint=AnyHttpUrl("https://example.com/oauth2/authorize"),
            token_endpoint=AnyHttpUrl("https://example.com/oauth2/token"),
        )
        serialized = json.loads(metadata.model_dump_json())
        assert serialized["issuer"] == "https://example.com/auth"
        assert not serialized["issuer"].endswith("/")

    def test_oauth_metadata_issuer_with_path_and_trailing_slash(self):
        """Issuer with path and trailing slash should only strip the trailing slash."""
        metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://example.com/auth/"),
            authorization_endpoint=AnyHttpUrl("https://example.com/oauth2/authorize"),
            token_endpoint=AnyHttpUrl("https://example.com/oauth2/token"),
        )
        serialized = json.loads(metadata.model_dump_json())
        assert serialized["issuer"] == "https://example.com/auth"

    def test_protected_resource_metadata_no_trailing_slash(self):
        """ProtectedResourceMetadata.resource should not have trailing slash."""
        metadata = ProtectedResourceMetadata(
            resource=AnyHttpUrl("https://example.com"),
            authorization_servers=[AnyHttpUrl("https://auth.example.com")],
        )
        serialized = json.loads(metadata.model_dump_json())
        assert serialized["resource"] == "https://example.com"
        assert not serialized["resource"].endswith("/")

    def test_protected_resource_metadata_auth_servers_no_trailing_slash(self):
        """ProtectedResourceMetadata.authorization_servers should not have trailing slashes."""
        metadata = ProtectedResourceMetadata(
            resource=AnyHttpUrl("https://example.com"),
            authorization_servers=[
                AnyHttpUrl("https://auth1.example.com"),
                AnyHttpUrl("https://auth2.example.com/path"),
            ],
        )
        serialized = json.loads(metadata.model_dump_json())
        assert serialized["authorization_servers"] == [
            "https://auth1.example.com",
            "https://auth2.example.com/path",
        ]
        for url in serialized["authorization_servers"]:
            assert not url.endswith("/")
