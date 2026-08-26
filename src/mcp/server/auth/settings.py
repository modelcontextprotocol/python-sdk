from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self


class ClientRegistrationOptions(BaseModel):
    enabled: bool = False
    client_secret_expiry_seconds: int | None = None
    valid_scopes: list[str] | None = None
    default_scopes: list[str] | None = None


class RevocationOptions(BaseModel):
    enabled: bool = False


class AuthSettings(BaseModel):
    # Preserve empty URL paths so a path-less issuer/resource passed as a string keeps its
    # canonical form (no trailing slash). RFC 8414/9207 issuer comparison is exact string
    # comparison, so a spurious trailing slash would break it. See PR #2925 for the metadata
    # models; this applies the same to the server's own configured URLs.
    model_config = ConfigDict(url_preserve_empty_path=True)

    issuer_url: AnyHttpUrl = Field(
        ...,
        description="OAuth authorization server URL that issues tokens for this resource server.",
    )
    service_documentation_url: AnyHttpUrl | None = None
    client_registration_options: ClientRegistrationOptions | None = None
    revocation_options: RevocationOptions | None = None
    required_scopes: list[str] | None = None
    identity_assertion_enabled: bool = Field(
        default=False,
        description="Advertise and accept the SEP-990 Identity Assertion Authorization Grant "
        "(the RFC 7523 jwt-bearer grant carrying an ID-JAG) at the token endpoint, for enterprise "
        "IdP flows. The provider must implement `exchange_identity_assertion`.",
    )

    # Resource Server settings (when operating as RS only)
    resource_server_url: AnyHttpUrl | None = Field(
        ...,
        description="The URL of the MCP server to be used as the resource identifier "
        "and base route to look up OAuth Protected Resource Metadata.",
    )
    validate_token_resource: bool = Field(
        default=False,
        description="Only accept tokens the token verifier reports as issued for `resource_server_url` "
        "(`AccessToken.resource`, the RFC 8707 resource indicator). Enable it when your authorization "
        "server binds tokens to the `resource` the client requested.",
    )

    @model_validator(mode="after")
    def _validate_token_resource_needs_a_resource(self) -> Self:
        if self.validate_token_resource and self.resource_server_url is None:
            raise ValueError("validate_token_resource requires resource_server_url")
        return self
