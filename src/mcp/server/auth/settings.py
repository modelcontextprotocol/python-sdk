from pydantic import AnyHttpUrl, BaseModel, Field


class ClientRegistrationOptions(BaseModel):
    enabled: bool = False
    client_secret_expiry_seconds: int | None = None
    valid_scopes: list[str] | None = None
    default_scopes: list[str] | None = None


class RevocationOptions(BaseModel):
    enabled: bool = False


class AuthSettings(BaseModel):
    issuer_url: AnyHttpUrl = Field(
        ...,
        description="OAuth authorization server URL that issues tokens for this resource server.",
    )
    service_documentation_url: AnyHttpUrl | None = None
    client_registration_options: ClientRegistrationOptions | None = None
    revocation_options: RevocationOptions | None = None
    required_scopes: list[str] | None = None
    cors_origin_regex: str | None = Field(
        default=None,
        description=(
            "Regex for allowed browser Origin values on the authorization server endpoints "
            "(/token, /register, /.well-known/oauth-authorization-server, etc). "
            "If unset, a safe default allows only loopback origins (localhost/127.0.0.1/[::1])."
        ),
    )

    # Resource Server settings (when operating as RS only)
    resource_server_url: AnyHttpUrl | None = Field(
        ...,
        description="The URL of the MCP server to be used as the resource identifier "
        "and base route to look up OAuth Protected Resource Metadata.",
    )
