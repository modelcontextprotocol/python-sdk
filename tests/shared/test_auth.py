"""Tests for OAuth 2.0 shared code."""

import pytest
from pydantic import AnyUrl, ValidationError

from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull, OAuthClientMetadata, OAuthMetadata


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
    """OAuthClientInformationFull shares the metadata base, so the same
    coercion applies to DCR responses parsed via the full model."""
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


# RFC 7591 §3.2.1 lets the authorization server reject or replace any requested metadata
# value in its registration response. Real servers echo values outside the sets the client
# would send (an unregistered application_type, an explicit null, an auth method the SDK
# does not implement, an empty redirect_uris array); a parse failure there discards a
# registration whose client_id the server has already provisioned.


@pytest.mark.parametrize(
    "substituted",
    [
        pytest.param({"application_type": "confidential"}, id="unregistered-application-type"),
        pytest.param({"application_type": ""}, id="empty-application-type"),
        pytest.param({"application_type": None}, id="null-application-type"),
        pytest.param({"token_endpoint_auth_method": "client_secret_jwt"}, id="unimplemented-auth-method"),
        pytest.param({"grant_types": ["authorization_code", "client_credentials"]}, id="extra-grant-type"),
        pytest.param({"redirect_uris": []}, id="empty-redirect-uris"),
    ],
)
def test_client_information_accepts_server_substituted_metadata(substituted: dict[str, object]):
    data = {"client_id": "abc123", "client_secret": "s3cr3t", **substituted}
    info = OAuthClientInformationFull.model_validate(data)
    assert info.client_id == "abc123"
    assert info.client_secret == "s3cr3t"


def test_client_information_without_echoed_metadata_still_parses():
    """A response holding only the credentials the server minted is a usable registration."""
    info = OAuthClientInformationFull.model_validate({"client_id": "abc123"})
    assert info.client_id == "abc123"
    assert info.redirect_uris is None
    assert info.application_type is None


def test_every_request_metadata_field_exists_on_the_client_record():
    """The registration handler builds its 201 echo from the request's dump; every request
    field must exist on the record so none can be silently dropped from the response."""
    assert set(OAuthClientMetadata.model_fields) <= set(OAuthClientInformationFull.model_fields)


def test_a_registration_response_without_a_client_id_is_rejected():
    """RFC 7591 §3.2.1 makes client_id REQUIRED; a body without one is not a registration,
    however permissive the parse is about the metadata around it."""
    with pytest.raises(ValidationError):
        OAuthClientInformationFull.model_validate({"application_type": "web"})


@pytest.mark.parametrize("placeholder", [None, ""], ids=["null", "empty-string"])
@pytest.mark.parametrize(
    "member",
    ["grant_types", "response_types", "redirect_uris", "application_type", "token_endpoint_auth_method", "scope"],
)
def test_client_information_reads_a_placeholder_member_as_an_omitted_key(member: str, placeholder: object):
    """A server that dumps unset members as null, or echoes them as "", still yields a
    usable registration: a placeholder and an absent key mean the same, so the field's
    default applies - including for list fields, where the placeholder is not a valid list."""
    info = OAuthClientInformationFull.model_validate({"client_id": "abc123", member: placeholder})
    defaults = OAuthClientInformationFull.model_validate({"client_id": "abc123"})
    assert getattr(info, member) == getattr(defaults, member)


def test_a_placeholder_client_id_is_a_missing_client_id():
    """The placeholder rule applies to the credential too: an empty client_id is no client_id,
    so the body is rejected rather than parsing as a registration with an empty identifier."""
    with pytest.raises(ValidationError):
        OAuthClientInformationFull.model_validate({"client_id": ""})


def test_client_information_that_is_not_an_object_still_fails_the_parse():
    """The null-as-omitted coercion only touches JSON objects; a body that is not one is
    passed through and rejected as a normal validation failure rather than swallowed."""
    with pytest.raises(ValidationError):
        OAuthClientInformationFull.model_validate("not-an-object")


@pytest.mark.parametrize("redirect_uris", [None, []], ids=["absent", "empty"])
@pytest.mark.parametrize(
    "redirect_uri", [None, AnyUrl("https://example.com/callback")], ids=["unspecified", "specified"]
)
def test_client_with_no_registered_redirect_uris_cannot_resolve_a_redirect(
    redirect_uris: list[str] | None, redirect_uri: AnyUrl | None
):
    """With no registered redirect URIs (absent or empty), no redirect resolves - neither a
    supplied one (nothing to match against) nor an unspecified one (no single default)."""
    info = OAuthClientInformationFull.model_validate({"client_id": "abc123", "redirect_uris": redirect_uris})
    with pytest.raises(InvalidRedirectUriError):
        info.validate_redirect_uri(redirect_uri)


def test_request_metadata_restricts_application_type_to_the_values_the_sdk_sends():
    """What the SDK sends stays narrow even though what it accepts back is wide."""
    with pytest.raises(ValidationError):
        OAuthClientMetadata.model_validate(
            {"redirect_uris": ["https://example.com/callback"], "application_type": "confidential"}
        )


def test_request_metadata_requires_at_least_one_redirect_uri():
    with pytest.raises(ValidationError):
        OAuthClientMetadata.model_validate({"redirect_uris": []})


def test_invalid_non_empty_url_still_rejected():
    """Coercion must only touch empty strings — garbage URLs still raise."""
    data = {
        "redirect_uris": ["https://example.com/callback"],
        "client_uri": "not a url",
    }
    with pytest.raises(ValidationError):
        OAuthClientMetadata.model_validate(data)
