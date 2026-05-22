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

    # Resource Server settings (when operating as RS only)
    resource_server_url: AnyHttpUrl | None = Field(
        ...,
        description=(
            "The full public URL of this MCP server, used as the resource identifier "
            "and base route to look up OAuth Protected Resource Metadata (RFC 9728). "
            "Must include the transport path (e.g. https://example.com/mcp for "
            "streamable-http, https://example.com/sse for sse) so that the value "
            "advertised in protected resource metadata exactly matches the URL the "
            "client used to reach the server. RFC 9728 §3.3 requires strict equality "
            "between the client's resource identifier and this value."
        ),
    )
