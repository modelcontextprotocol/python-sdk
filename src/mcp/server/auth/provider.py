from dataclasses import dataclass
from typing import Any, Generic, Literal, Protocol, TypeVar
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from pydantic import AnyUrl, BaseModel

from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class AuthorizationParams(BaseModel):
    state: str | None
    scopes: list[str] | None
    code_challenge: str
    redirect_uri: AnyUrl
    redirect_uri_provided_explicitly: bool
    resource: str | None = None  # RFC 8707 resource indicator


class IdentityAssertionParams(BaseModel):
    """Validated parameters of a SEP-990 identity-assertion (RFC 7523 jwt-bearer) request.

    Passed to `OAuthAuthorizationServerProvider.exchange_identity_assertion`; `assertion` is the
    ID-JAG (a signed JWT) issued by the enterprise identity provider.
    """

    assertion: str  # RFC 7523 §2.1: the JWT (ID-JAG) presented as the authorization grant
    scopes: list[str] | None = None
    resource: str | None = None  # RFC 8707 resource indicator from the token request


class AuthorizationCode(BaseModel):
    code: str
    scopes: list[str]
    expires_at: float
    client_id: str
    code_challenge: str
    redirect_uri: AnyUrl
    redirect_uri_provided_explicitly: bool
    resource: str | None = None  # RFC 8707 resource indicator
    subject: str | None = None  # resource owner; propagate to the issued AccessToken


class RefreshToken(BaseModel):
    token: str
    client_id: str
    scopes: list[str]
    expires_at: int | None = None
    subject: str | None = None  # resource owner; propagate to refreshed AccessTokens


class AccessToken(BaseModel):
    token: str
    client_id: str
    scopes: list[str]
    expires_at: int | None = None
    resource: str | None = None  # RFC 8707 resource indicator
    subject: str | None = None  # RFC 7662/9068 `sub`: resource owner; unique only per issuer
    claims: dict[str, Any] | None = None  # additional claims (e.g. `iss`, `act`)


RegistrationErrorCode = Literal[
    "invalid_redirect_uri",
    "invalid_client_metadata",
    "invalid_software_statement",
    "unapproved_software_statement",
]


@dataclass(frozen=True)
class RegistrationError(Exception):
    error: RegistrationErrorCode
    error_description: str | None = None


AuthorizationErrorCode = Literal[
    "invalid_request",
    "unauthorized_client",
    "access_denied",
    "unsupported_response_type",
    "invalid_scope",
    "server_error",
    "temporarily_unavailable",
    "invalid_target",
]


@dataclass(frozen=True)
class AuthorizeError(Exception):
    error: AuthorizationErrorCode
    error_description: str | None = None


TokenErrorCode = Literal[
    "invalid_request",
    "invalid_client",
    "invalid_grant",
    "unauthorized_client",
    "unsupported_grant_type",
    "invalid_scope",
    # RFC 8707 §2: the requested resource indicator is unknown or unsupported.
    "invalid_target",
]


@dataclass(frozen=True)
class TokenError(Exception):
    error: TokenErrorCode
    error_description: str | None = None


class TokenVerifier(Protocol):
    """Protocol for verifying bearer tokens."""

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a bearer token and return access info if valid."""


# MCPServer never renders these types in user responses, so subclasses may add fields not meant for external exposure.
AuthorizationCodeT = TypeVar("AuthorizationCodeT", bound=AuthorizationCode)
RefreshTokenT = TypeVar("RefreshTokenT", bound=RefreshToken)
AccessTokenT = TypeVar("AccessTokenT", bound=AccessToken)


class OAuthAuthorizationServerProvider(Protocol, Generic[AuthorizationCodeT, RefreshTokenT, AccessTokenT]):
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Retrieve client information by client ID, or None if the client does not exist.

        Implementors MAY raise NotImplementedError if dynamic client registration is
        disabled in ClientRegistrationOptions.
        """

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Save client information as part of registering it.

        Implementors MAY raise NotImplementedError if dynamic client registration is
        disabled in ClientRegistrationOptions.

        Raises:
            RegistrationError: If the client metadata is invalid.
        """

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Handle the /authorize endpoint and return the URL to redirect the client to.

        Many MCP implementations redirect here to a third-party OAuth provider for a second
        exchange (client <-> MCP server <-> third-party server). Such setups need another
        handler on the return flow that generates and stores an authorization code and
        finally redirects the client to `params.redirect_uri`.

        Authorization codes MUST have at least 128 bits of entropy and SHOULD have at least
        160 (https://datatracker.ietf.org/doc/html/rfc6749#section-10.10).

        Raises:
            AuthorizeError: If the authorization request is invalid.
        """
        ...

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCodeT | None:
        """Load an AuthorizationCode by its code string, or None if not found."""
        ...

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCodeT
    ) -> OAuthToken:
        """Exchange an authorization code for an access token and refresh token.

        Raises:
            TokenError: If the request is invalid.
        """
        ...

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshTokenT | None:
        """Load a RefreshToken by its token string, or None if not found."""
        ...

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshTokenT,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchange a refresh token for an access token and refresh token.

        Implementations SHOULD rotate both the access token and refresh token.

        Raises:
            TokenError: If the request is invalid.
        """
        ...

    async def load_access_token(self, token: str) -> AccessTokenT | None:
        """Load an access token by its token string, or None if the token is invalid."""

    async def revoke_token(
        self,
        token: AccessTokenT | RefreshTokenT,
    ) -> None:
        """Revoke an access or refresh token; do nothing if it is invalid or already revoked.

        Implementations SHOULD revoke both the access token and its corresponding refresh
        token, regardless of which one is provided.
        """

    async def exchange_identity_assertion(
        self,
        client: OAuthClientInformationFull,
        params: IdentityAssertionParams,
    ) -> OAuthToken:
        """Exchange an Identity Assertion Authorization Grant (ID-JAG) for an access token.

        Leg 2 of SEP-990: the client presents an IdP-issued ID-JAG via the RFC 7523
        `urn:ietf:params:oauth:grant-type:jwt-bearer` grant and receives an access token for
        this MCP server. The default implementation rejects every request as an unsupported
        grant type; override it to enable the grant.

        The implementation must validate `params.assertion` per RFC 7523 §3 and the
        SEP-990 §5.1 processing rules, in particular:

        - verify the JWT signature, `iss`, and `exp`, and that `typ` is `oauth-id-jag+jwt`;
        - require `aud` to identify this authorization server (its own issuer);
        - require a `sub` (mandatory per RFC 7523 §3) identifying the end user;
        - reject replays: enforce `exp` and track `jti` for the assertion's lifetime;
        - require the ID-JAG's `client_id` claim to match the authenticated `client`; do NOT
          derive authorization from `client.client_id` alone, which is ultimately
          self-asserted in the request even for an authenticated confidential client;
        - audience-restrict the issued access token to the ID-JAG's `resource` claim, not
          merely `params.resource` (which the client controls);
        - derive the granted scopes from the ID-JAG and policy rather than granting
          `params.scopes` verbatim.

        The handler guarantees `client` is confidential (it rejects clients without a stored
        secret before calling this hook), but the ID-JAG remains the authoritative grant.

        Returns:
            The OAuth token. A refresh token SHOULD NOT be issued: SEP-990 relies on the IdP
            to control session lifetime via re-issued ID-JAGs.

        Raises:
            TokenError: If the assertion or request is invalid. Use `invalid_grant` for a
                rejected assertion and `invalid_target` for an unknown `resource`.
        """
        raise TokenError(
            error="unsupported_grant_type",
            error_description="The JWT bearer grant is not supported by this authorization server",
        )


def construct_redirect_uri(redirect_uri_base: str, **params: str | None) -> str:
    parsed_uri = urlparse(redirect_uri_base)
    query_params = [(k, v) for k, vs in parse_qs(parsed_uri.query).items() for v in vs]
    for k, v in params.items():
        if v is not None:
            query_params.append((k, v))

    redirect_uri = urlunparse(parsed_uri._replace(query=urlencode(query_params)))
    return redirect_uri


class ProviderTokenVerifier(TokenVerifier):
    """Token verifier backed by an OAuthAuthorizationServerProvider.

    Provided for backwards compatibility with existing auth_server_provider configurations;
    new AS/RS-separated implementations should prefer a dedicated TokenVerifier such as
    IntrospectionTokenVerifier.
    """

    def __init__(self, provider: "OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]"):
        self.provider = provider

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token using the provider's load_access_token method."""
        return await self.provider.load_access_token(token)
