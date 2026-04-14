"""Tests for OAuth 2.0 shared code."""

import pytest
from pydantic import ValidationError

from mcp.shared.auth import InvalidScopeError, OAuthClientInformationFull, OAuthClientMetadata, OAuthMetadata


def _make_client(scope: str | None) -> OAuthClientInformationFull:
    return OAuthClientInformationFull.model_validate(
        {
            "redirect_uris": ["https://example.com/callback"],
            "scope": scope,
            "client_id": "test-client",
        }
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


# RFC 7591 §2 marks client_uri/logo_uri/tos_uri/policy_uri/jwks_uri as OPTIONAL.
# Some authorization servers echo the client's omitted metadata back as ""
# instead of dropping the keys; without coercion, AnyHttpUrl rejects "" and
# the whole registration response is thrown away even though the server
# returned a valid client_id.


@pytest.mark.parametrize(
    "empty_field",
    ["client_uri", "logo_uri", "tos_uri", "policy_uri", "jwks_uri"],
)
def test_optional_url_empty_string_coerced_to_none(empty_field: str):
    data = {
        "redirect_uris": ["https://example.com/callback"],
        empty_field: "",
    }
    metadata = OAuthClientMetadata.model_validate(data)
    assert getattr(metadata, empty_field) is None


def test_all_optional_urls_empty_together():
    data = {
        "redirect_uris": ["https://example.com/callback"],
        "client_uri": "",
        "logo_uri": "",
        "tos_uri": "",
        "policy_uri": "",
        "jwks_uri": "",
    }
    metadata = OAuthClientMetadata.model_validate(data)
    assert metadata.client_uri is None
    assert metadata.logo_uri is None
    assert metadata.tos_uri is None
    assert metadata.policy_uri is None
    assert metadata.jwks_uri is None


def test_valid_url_passes_through_unchanged():
    data = {
        "redirect_uris": ["https://example.com/callback"],
        "client_uri": "https://udemy.com/",
    }
    metadata = OAuthClientMetadata.model_validate(data)
    assert str(metadata.client_uri) == "https://udemy.com/"


def test_information_full_inherits_coercion():
    """OAuthClientInformationFull subclasses OAuthClientMetadata, so the
    same coercion applies to DCR responses parsed via the full model."""
    data = {
        "client_id": "abc123",
        "redirect_uris": ["https://example.com/callback"],
        "client_uri": "",
        "logo_uri": "",
        "tos_uri": "",
        "policy_uri": "",
        "jwks_uri": "",
    }
    info = OAuthClientInformationFull.model_validate(data)
    assert info.client_id == "abc123"
    assert info.client_uri is None
    assert info.logo_uri is None
    assert info.tos_uri is None
    assert info.policy_uri is None
    assert info.jwks_uri is None


def test_invalid_non_empty_url_still_rejected():
    """Coercion must only touch empty strings — garbage URLs still raise."""
    data = {
        "redirect_uris": ["https://example.com/callback"],
        "client_uri": "not a url",
    }
    with pytest.raises(ValidationError):
        OAuthClientMetadata.model_validate(data)
