from typing import Any, Literal, cast

from pydantic import (
    AnyHttpUrl,
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidatorFunctionWrapHandler,
    field_validator,
    model_validator,
)

# `url_preserve_empty_path` (pydantic >= 2.12) keeps a path-less URL from gaining a trailing slash when
# parsed from the wire, so issuer/resource identifiers round-trip as transmitted (RFC 3986 §6.2.1 simple
# string comparison). Older pydantic ignores unknown config keys at runtime; the cast keeps the 2.11 type
# stubs (which do not know the key) quiet. See `ProtectedResourceMetadata.resource_str` for the
# version-independent path used for the RFC 8707 `resource` parameter.
_PRESERVE_EMPTY_PATH = cast(ConfigDict, {"url_preserve_empty_path": True})


class OAuthToken(BaseModel):
    """
    See https://datatracker.ietf.org/doc/html/rfc6749#section-5.1
    """

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


class InvalidScopeError(Exception):
    def __init__(self, message: str):
        self.message = message


class InvalidRedirectUriError(Exception):
    def __init__(self, message: str):
        self.message = message


class OAuthClientMetadata(BaseModel):
    """
    RFC 7591 OAuth 2.0 Dynamic Client Registration metadata.
    See https://datatracker.ietf.org/doc/html/rfc7591#section-2
    for the full specification.
    """

    model_config = _PRESERVE_EMPTY_PATH

    redirect_uris: list[AnyUrl] | None = Field(..., min_length=1)
    # supported auth methods for the token endpoint
    token_endpoint_auth_method: (
        Literal["none", "client_secret_post", "client_secret_basic", "private_key_jwt"] | None
    ) = None
    # supported grant_types of this implementation
    grant_types: list[
        Literal["authorization_code", "refresh_token", "urn:ietf:params:oauth:grant-type:jwt-bearer"] | str
    ] = [
        "authorization_code",
        "refresh_token",
    ]
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
        # RFC 7591 §2 marks these URL fields OPTIONAL. Some authorization servers
        # echo omitted metadata back as "" instead of dropping the keys, which
        # AnyHttpUrl would otherwise reject — throwing away an otherwise valid
        # registration response. Treat "" as absent.
        if v == "":
            return None
        return v

    def validate_scope(self, requested_scope: str | None) -> list[str] | None:
        if requested_scope is None:
            return None
        requested_scopes = requested_scope.split(" ")
        allowed_scopes = [] if self.scope is None else self.scope.split(" ")
        for scope in requested_scopes:
            if scope not in allowed_scopes:  # pragma: no branch
                raise InvalidScopeError(f"Client was not registered with scope {scope}")
        return requested_scopes  # pragma: no cover

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is not None:
            # Validate redirect_uri against client's registered redirect URIs
            if self.redirect_uris is None or redirect_uri not in self.redirect_uris:
                raise InvalidRedirectUriError(f"Redirect URI '{redirect_uri}' not registered for client")
            return redirect_uri
        elif self.redirect_uris is not None and len(self.redirect_uris) == 1:
            return self.redirect_uris[0]
        else:
            raise InvalidRedirectUriError("redirect_uri must be specified when client has multiple registered URIs")


class OAuthClientInformationFull(OAuthClientMetadata):
    """
    RFC 7591 OAuth 2.0 Dynamic Client Registration full response
    (client information plus metadata).
    """

    client_id: str | None = None
    client_secret: str | None = None
    client_id_issued_at: int | None = None
    client_secret_expires_at: int | None = None
    # SEP-2352: the issuer these credentials were registered with, recorded by the SDK (not an
    # RFC 7591 field) to detect authorization-server migration and avoid cross-AS credential reuse.
    issuer: str | None = None


class OAuthMetadata(BaseModel):
    """
    RFC 8414 OAuth 2.0 Authorization Server Metadata.
    See https://datatracker.ietf.org/doc/html/rfc8414#section-2
    """

    model_config = _PRESERVE_EMPTY_PATH

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


class ProtectedResourceMetadata(BaseModel):
    """
    RFC 9728 OAuth 2.0 Protected Resource Metadata.
    See https://datatracker.ietf.org/doc/html/rfc9728#section-2
    """

    model_config = _PRESERVE_EMPTY_PATH

    resource: AnyHttpUrl
    authorization_servers: list[AnyHttpUrl] = Field(..., min_length=1)
    # The `resource` value exactly as received. `url_preserve_empty_path` only takes effect on
    # pydantic >= 2.12; on older pydantic a path-less URL still renders with a trailing slash, which
    # breaks the byte-exact RFC 8707 `resource` parameter. Kept alongside the parsed URL so callers
    # can echo the server's identifier verbatim regardless of pydantic version.
    _resource_raw: str | None = PrivateAttr(default=None)

    @model_validator(mode="wrap")
    @classmethod
    def _capture_raw_resource(cls, data: Any, handler: ValidatorFunctionWrapHandler) -> "ProtectedResourceMetadata":
        raw: Any = cast(dict[str, Any], data).get("resource") if isinstance(data, dict) else None
        model = cast("ProtectedResourceMetadata", handler(data))
        if isinstance(raw, str):
            model._resource_raw = raw
        return model

    @property
    def resource_str(self) -> str:
        """The resource identifier as a string, exactly as the server published it when parsed from
        JSON/dict input (RFC 8707 requires clients to send it byte-for-byte); otherwise the rendered URL."""
        return self._resource_raw if self._resource_raw is not None else str(self.resource)

    jwks_uri: AnyHttpUrl | None = None
    scopes_supported: list[str] | None = None
    bearer_methods_supported: list[str] | None = Field(default=["header"])  # MCP only supports header method
    resource_signing_alg_values_supported: list[str] | None = None
    resource_name: str | None = None
    resource_documentation: AnyHttpUrl | None = None
    resource_policy_uri: AnyHttpUrl | None = None
    resource_tos_uri: AnyHttpUrl | None = None
    # tls_client_certificate_bound_access_tokens default is False, but ommited here for clarity
    tls_client_certificate_bound_access_tokens: bool | None = None
    authorization_details_types_supported: list[str] | None = None
    dpop_signing_alg_values_supported: list[str] | None = None
    # dpop_bound_access_tokens_required default is False, but ommited here for clarity
    dpop_bound_access_tokens_required: bool | None = None
