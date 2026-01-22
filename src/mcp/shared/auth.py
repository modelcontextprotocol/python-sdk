from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import AnyHttpUrl, AnyUrl, BaseModel, Field, field_validator


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


class InvalidScopeError(Exception):
    def __init__(self, message: str):
        self.message = message


class InvalidRedirectUriError(Exception):
    def __init__(self, message: str):
        self.message = message


class OAuthClientMetadata(BaseModel):
    """RFC 7591 OAuth 2.0 Dynamic Client Registration metadata.
    See https://datatracker.ietf.org/doc/html/rfc7591#section-2
    for the full specification.
    """

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
        """Validate redirect_uri against client's registered URIs.
        
        Implements RFC 8252 Section 7.3 for loopback addresses:
        "The authorization server MUST allow any port to be specified at the time
        of the request for loopback IP redirect URIs, to accommodate clients that
        obtain an available ephemeral port from the operating system at the time
        of the request."
        
        For loopback addresses (localhost, 127.0.0.1, ::1), the port is ignored
        during validation. For all other URIs, exact matching is required.
        
        Args:
            redirect_uri: The redirect_uri from the authorization request
            
        Returns:
            The validated redirect_uri
            
        Raises:
            InvalidRedirectUriError: If redirect_uri is invalid or not registered
        """
        if redirect_uri is not None:
            if self.redirect_uris is None:
                raise InvalidRedirectUriError("No redirect URIs registered for client")
            
            # Try exact match first (fast path)
            if redirect_uri in self.redirect_uris:
                return redirect_uri
            
            # RFC 8252 loopback matching: ignore port for localhost/127.0.0.1/::1
            requested_str = str(redirect_uri)
            parsed_requested = urlparse(requested_str)
            is_loopback = parsed_requested.hostname in ("localhost", "127.0.0.1", "::1", "[::1]")
            
            if is_loopback:
                for registered in self.redirect_uris:
                    parsed_registered = urlparse(str(registered))
                    if parsed_registered.hostname not in ("localhost", "127.0.0.1", "::1", "[::1]"):
                        continue
                    # Match scheme, hostname, and path - port can differ per RFC 8252
                    if (parsed_requested.scheme == parsed_registered.scheme and
                        parsed_requested.hostname == parsed_registered.hostname and
                        (parsed_requested.path or "/") == (parsed_registered.path or "/")):
                        return redirect_uri
            
            raise InvalidRedirectUriError(f"Redirect URI '{redirect_uri}' not registered for client")
        elif self.redirect_uris is not None and len(self.redirect_uris) == 1:
            return self.redirect_uris[0]
        else:
            raise InvalidRedirectUriError("redirect_uri must be specified when client has multiple registered URIs")


class OAuthClientInformationFull(OAuthClientMetadata):
    """RFC 7591 OAuth 2.0 Dynamic Client Registration full response
    (client information plus metadata).
    """

    client_id: str | None = None
    client_secret: str | None = None
    client_id_issued_at: int | None = None
    client_secret_expires_at: int | None = None


class OAuthMetadata(BaseModel):
    """RFC 8414 OAuth 2.0 Authorization Server Metadata.
    See https://datatracker.ietf.org/doc/html/rfc8414#section-2
    """

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
    """RFC 9728 OAuth 2.0 Protected Resource Metadata.
    See https://datatracker.ietf.org/doc/html/rfc9728#section-2
    """

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
    # tls_client_certificate_bound_access_tokens default is False, but ommited here for clarity
    tls_client_certificate_bound_access_tokens: bool | None = None
    authorization_details_types_supported: list[str] | None = None
    dpop_signing_alg_values_supported: list[str] | None = None
    # dpop_bound_access_tokens_required default is False, but ommited here for clarity
    dpop_bound_access_tokens_required: bool | None = None
