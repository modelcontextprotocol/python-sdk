from typing import Any, Literal, cast

from pydantic import AnyHttpUrl, AnyUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

# RFC 7523 JWT bearer grant; SEP-990 leg 2 uses this to present the ID-JAG.
JWT_BEARER_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"

# Token-endpoint client authentication methods this SDK's clients request, and the set
# `OAuthContext.prepare_token_auth` recognizes on a registered client (`private_key_jwt` is
# applied by `PrivateKeyJWTOAuthProvider`; the rest send a client secret or nothing).
TokenEndpointAuthMethod = Literal["none", "client_secret_post", "client_secret_basic", "private_key_jwt"]

# grant_types a client requests when it does not specify its own (RFC 7591 §2).
DEFAULT_GRANT_TYPES = ["authorization_code", "refresh_token"]


def _empty_str_to_none(v: object) -> object:
    # RFC 7591 §2 marks these URL fields OPTIONAL; a "" placeholder means absent, so it
    # must not fail AnyHttpUrl validation. (The registered-client record applies the same
    # rule to every member; this coercion serves the request model.)
    if v == "":
        return None
    return v


class OAuthToken(BaseModel):
    """See https://datatracker.ietf.org/doc/html/rfc6749#section-5.1"""

    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int | None = None
    scope: str | None = None
    refresh_token: str | None = None

    @field_validator("token_type", mode="before")
    @classmethod
    def normalize_token_type(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            # Bearer is title-cased in the spec, so we normalize it
            # https://datatracker.ietf.org/doc/html/rfc6750#section-4
            return v.title()
        return v  # pragma: no cover


class AuthorizationCodeResult(BaseModel):
    """Authorization-code-grant redirect parameters returned by a callback handler.

    `iss` carries the RFC 9207 authorization-response issuer when the authorization server
    includes it in the redirect; the client validates it against the expected issuer.
    """

    code: str
    state: str | None = None
    iss: str | None = None


class InvalidScopeError(Exception):
    def __init__(self, message: str):
        self.message = message


class InvalidRedirectUriError(Exception):
    def __init__(self, message: str):
        self.message = message


class OAuthClientMetadataBase(BaseModel):
    """RFC 7591 OAuth 2.0 Dynamic Client Registration metadata shared verbatim by the
    registration request (`OAuthClientMetadata`) and the authorization server's record of a
    registered client (`OAuthClientInformationFull`). Fields whose acceptable values differ
    between the two - what this SDK sends versus what a third-party server may echo - are
    declared on each model rather than here.
    See https://datatracker.ietf.org/doc/html/rfc7591#section-2
    """

    model_config = ConfigDict(url_preserve_empty_path=True)

    # The MCP spec requires the "code" response type, but OAuth
    # servers may also return additional types they support
    response_types: list[str] = ["code"]
    scope: str | None = None

    # these fields are currently unused, but we support & store them for potential
    # future use
    client_name: str | None = None
    client_uri: AnyHttpUrl | None = None
    logo_uri: AnyHttpUrl | None = None
    contacts: list[str] | None = None
    tos_uri: AnyHttpUrl | None = None
    policy_uri: AnyHttpUrl | None = None
    jwks_uri: AnyHttpUrl | None = None
    jwks: Any | None = None
    software_id: str | None = None
    software_version: str | None = None

    @field_validator(
        "client_uri",
        "logo_uri",
        "tos_uri",
        "policy_uri",
        "jwks_uri",
        mode="before",
    )
    @classmethod
    def _empty_string_optional_url_to_none(cls, v: object) -> object:
        # These URL fields are OPTIONAL; an echoed "" would otherwise fail AnyHttpUrl
        # and throw away an otherwise valid registration response.
        return _empty_str_to_none(v)


class OAuthClientMetadata(OAuthClientMetadataBase):
    """RFC 7591 OAuth 2.0 Dynamic Client Registration request metadata: what an MCP
    client sends when it registers. Field values are narrowed to what this SDK will put
    on the wire; parsing the authorization server's response is `OAuthClientInformationFull`'s
    job. See https://datatracker.ietf.org/doc/html/rfc7591#section-2
    """

    redirect_uris: list[AnyUrl] | None = Field(..., min_length=1)
    # supported auth methods for the token endpoint
    token_endpoint_auth_method: TokenEndpointAuthMethod | None = None
    # supported grant_types of this implementation
    grant_types: list[
        Literal["authorization_code", "refresh_token", "urn:ietf:params:oauth:grant-type:jwt-bearer"] | str
    ] = list(DEFAULT_GRANT_TYPES)
    # SEP-837: OIDC application_type. Defaults to "native" since MCP clients typically use
    # loopback redirect URIs; set "web" for remote browser-based clients on a non-local host.
    application_type: Literal["web", "native"] = "native"


class OAuthClientInformationFull(OAuthClientMetadataBase):
    """RFC 7591 OAuth 2.0 Dynamic Client Registration client information response
    (client information plus metadata) - the authorization server's record of a
    registered client. See https://datatracker.ietf.org/doc/html/rfc7591#section-3.2.1

    A third-party authorization server "MAY reject or replace any of the client's
    requested metadata values submitted during the registration and substitute them with
    suitable values", so `application_type`, `token_endpoint_auth_method`, and `grant_types`
    are typed to accept any string the server echoes, and `redirect_uris` may be absent or
    empty. A member the server serializes as a placeholder - an explicit `null`, or `""` -
    is read as an omitted key, so the field's default applies rather than the parse failing.
    Whether a substituted value is usable is decided where the value is used, not at parse.
    `redirect_uris` elements are still parsed as URLs, as the authorization server compares
    them against a client's requested `redirect_uri`.
    """

    redirect_uris: list[AnyUrl] | None = None
    # RFC 7591 §3.2.1: the server may assign an auth method other than the one requested,
    # including methods this SDK does not implement, or omit it.
    token_endpoint_auth_method: str | None = None
    grant_types: list[str] = list(DEFAULT_GRANT_TYPES)
    # SEP-837: OIDC application_type. OIDC Registration §2 defines "web" and "native", but
    # servers echo other strings or an explicit null; the value is informational here.
    application_type: str | None = None

    # RFC 7591 §3.2.1: client_id is REQUIRED in a client information response - a body
    # without one is not a registration, whatever else it echoes.
    client_id: str
    client_secret: str | None = None
    client_id_issued_at: int | None = None
    client_secret_expires_at: int | None = None
    # SEP-2352: the issuer these credentials were registered with, recorded by the SDK (not an
    # RFC 7591 field) to detect authorization-server migration and avoid cross-AS credential reuse.
    issuer: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _placeholder_members_read_as_omitted(cls, data: object) -> object:
        # Servers dump unset members of their client record as null, or echo them as "",
        # instead of omitting the keys. Either placeholder would otherwise fail the parse of a
        # list field (or read "" as an unrecognized method) and discard an already-provisioned
        # registration; a placeholder and an absent key mean the same thing.
        if isinstance(data, dict):
            members = cast(dict[str, Any], data)
            return {key: value for key, value in members.items() if value is not None and value != ""}
        return data

    def validate_scope(self, requested_scope: str | None) -> list[str] | None:
        if requested_scope is None:
            return None
        requested_scopes = requested_scope.split(" ")
        allowed_scopes = [] if self.scope is None else self.scope.split(" ")
        for scope in requested_scopes:
            if scope not in allowed_scopes:
                raise InvalidScopeError(f"Client was not registered with scope {scope}")
        return requested_scopes

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is not None:
            # Validate redirect_uri against client's registered redirect URIs
            if not self.redirect_uris or redirect_uri not in self.redirect_uris:
                raise InvalidRedirectUriError(f"Redirect URI '{redirect_uri}' not registered for client")
            return redirect_uri
        elif self.redirect_uris and len(self.redirect_uris) == 1:
            return self.redirect_uris[0]
        else:
            raise InvalidRedirectUriError(
                "redirect_uri must be specified unless the client has exactly one registered URI"
            )


class OAuthMetadata(BaseModel):
    """RFC 8414 OAuth 2.0 Authorization Server Metadata.
    See https://datatracker.ietf.org/doc/html/rfc8414#section-2
    """

    model_config = ConfigDict(url_preserve_empty_path=True)

    issuer: AnyHttpUrl
    authorization_endpoint: AnyHttpUrl
    token_endpoint: AnyHttpUrl
    registration_endpoint: AnyHttpUrl | None = None
    scopes_supported: list[str] | None = None
    response_types_supported: list[str] = ["code"]
    response_modes_supported: list[str] | None = None
    grant_types_supported: list[str] | None = None
    token_endpoint_auth_methods_supported: list[str] | None = None
    token_endpoint_auth_signing_alg_values_supported: list[str] | None = None
    service_documentation: AnyHttpUrl | None = None
    ui_locales_supported: list[str] | None = None
    op_policy_uri: AnyHttpUrl | None = None
    op_tos_uri: AnyHttpUrl | None = None
    revocation_endpoint: AnyHttpUrl | None = None
    revocation_endpoint_auth_methods_supported: list[str] | None = None
    revocation_endpoint_auth_signing_alg_values_supported: list[str] | None = None
    introspection_endpoint: AnyHttpUrl | None = None
    introspection_endpoint_auth_methods_supported: list[str] | None = None
    introspection_endpoint_auth_signing_alg_values_supported: list[str] | None = None
    code_challenge_methods_supported: list[str] | None = None
    client_id_metadata_document_supported: bool | None = None
    authorization_response_iss_parameter_supported: bool | None = None
    # SEP-990 / draft-ietf-oauth-identity-assertion-authz-grant §7.2: profiles whose grants the
    # authorization server supports, e.g. `urn:ietf:params:oauth:grant-profile:id-jag`.
    authorization_grant_profiles_supported: list[str] | None = None


class ProtectedResourceMetadata(BaseModel):
    """RFC 9728 OAuth 2.0 Protected Resource Metadata.
    See https://datatracker.ietf.org/doc/html/rfc9728#section-2
    """

    model_config = ConfigDict(url_preserve_empty_path=True)

    resource: AnyHttpUrl
    authorization_servers: list[AnyHttpUrl] = Field(..., min_length=1)
    jwks_uri: AnyHttpUrl | None = None
    scopes_supported: list[str] | None = None
    bearer_methods_supported: list[str] | None = Field(default=["header"])  # MCP only supports header method
    resource_signing_alg_values_supported: list[str] | None = None
    resource_name: str | None = None
    resource_documentation: AnyHttpUrl | None = None
    resource_policy_uri: AnyHttpUrl | None = None
    resource_tos_uri: AnyHttpUrl | None = None
    # tls_client_certificate_bound_access_tokens default is False, but omitted here for clarity
    tls_client_certificate_bound_access_tokens: bool | None = None
    authorization_details_types_supported: list[str] | None = None
    dpop_signing_alg_values_supported: list[str] | None = None
    # dpop_bound_access_tokens_required default is False, but omitted here for clarity
    dpop_bound_access_tokens_required: bool | None = None
