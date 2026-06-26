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


class TokenExchangeParams(BaseModel):
    """Validated parameters of an RFC 8693 token-exchange request.

    Passed to ``OAuthAuthorizationServerProvider.exchange_token``. The subject token is the
    security token the client is exchanging - for SEP-990 this is the ID-JAG issued by the
    enterprise identity provider.
    """

    subject_token: str  # RFC 8693 §2.1: the security token being exchanged
    subject_token_type: str  # RFC 8693 §2.1: type identifier of the subject token
    requested_token_type: str | None = None  # RFC 8693 §2.1: desired type of the issued token
    actor_token: str | None = None  # RFC 8693 §2.1: token of the acting party, for delegation
    actor_token_type: str | None = None  # RFC 8693 §2.1: type identifier of the actor token
    scopes: list[str] | None = None
    resource: str | None = None  # RFC 8707 resource indicator
    audience: str | None = None  # RFC 8693 §2.1: logical name of the target service


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
    # RFC 8693 §2.2.2: the requested resource/audience target is unknown or unsupported.
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


# NOTE: MCPServer doesn't render any of these types in the user response, so it's
# OK to add fields to subclasses which should not be exposed externally.
AuthorizationCodeT = TypeVar("AuthorizationCodeT", bound=AuthorizationCode)
RefreshTokenT = TypeVar("RefreshTokenT", bound=RefreshToken)
AccessTokenT = TypeVar("AccessTokenT", bound=AccessToken)


class OAuthAuthorizationServerProvider(Protocol, Generic[AuthorizationCodeT, RefreshTokenT, AccessTokenT]):
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Retrieves client information by client ID.

        Implementors MAY raise NotImplementedError if dynamic client registration is
        disabled in ClientRegistrationOptions.

        Args:
            client_id: The ID of the client to retrieve.

        Returns:
            The client information, or None if the client does not exist.
        """

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Saves client information as part of registering it.

        Implementors MAY raise NotImplementedError if dynamic client registration is
        disabled in ClientRegistrationOptions.

        Args:
            client_info: The client metadata to register.

        Raises:
            RegistrationError: If the client metadata is invalid.
        """

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Handle the /authorize endpoint and return a URL that the client
        will be redirected to.

        Many MCP implementations will redirect to a third-party provider to perform
        a second OAuth exchange with that provider. In this sort of setup, the client
        has an OAuth connection with the MCP server, and the MCP server has an OAuth
        connection with the 3rd-party provider. At the end of this flow, the client
        should be redirected to the redirect_uri from params.redirect_uri.

        +--------+     +------------+     +-------------------+
        |        |     |            |     |                   |
        | Client | --> | MCP Server | --> | 3rd Party OAuth   |
        |        |     |            |     | Server            |
        +--------+     +------------+     +-------------------+
                            |   ^                  |
        +------------+      |   |                  |
        |            |      |   |    Redirect      |
        |redirect_uri|<-----+   +------------------+
        |            |
        +------------+

        Implementations will need to define another handler on the MCP server's return
        flow to perform the second redirect, and generate and store an authorization
        code as part of completing the OAuth authorization step.

        Implementations SHOULD generate an authorization code with at least 160 bits of
        entropy,
        and MUST generate an authorization code with at least 128 bits of entropy.
        See https://datatracker.ietf.org/doc/html/rfc6749#section-10.10.

        Args:
            client: The client requesting authorization.
            params: The parameters of the authorization request.

        Returns:
            A URL to redirect the client to for authorization.

        Raises:
            AuthorizeError: If the authorization request is invalid.
        """
        ...

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCodeT | None:
        """Loads an AuthorizationCode by its code.

        Args:
            client: The client that requested the authorization code.
            authorization_code: The authorization code to get the challenge for.

        Returns:
            The AuthorizationCode, or None if not found.
        """
        ...

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCodeT
    ) -> OAuthToken:
        """Exchanges an authorization code for an access token and refresh token.

        Args:
            client: The client exchanging the authorization code.
            authorization_code: The authorization code to exchange.

        Returns:
            The OAuth token, containing access and refresh tokens.

        Raises:
            TokenError: If the request is invalid.
        """
        ...

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshTokenT | None:
        """Loads a RefreshToken by its token string.

        Args:
            client: The client that is requesting to load the refresh token.
            refresh_token: The refresh token string to load.

        Returns:
            The RefreshToken object if found, or None if not found.
        """
        ...

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshTokenT,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchanges a refresh token for an access token and refresh token.

        Implementations SHOULD rotate both the access token and refresh token.

        Args:
            client: The client exchanging the refresh token.
            refresh_token: The refresh token to exchange.
            scopes: Optional scopes to request with the new access token.

        Returns:
            The OAuth token, containing access and refresh tokens.

        Raises:
            TokenError: If the request is invalid.
        """
        ...

    async def load_access_token(self, token: str) -> AccessTokenT | None:
        """Loads an access token by its token string.

        Args:
            token: The access token to verify.

        Returns:
            The access token, or None if the token is invalid.
        """

    async def revoke_token(
        self,
        token: AccessTokenT | RefreshTokenT,
    ) -> None:
        """Revokes an access or refresh token.

        If the given token is invalid or already revoked, this method should do nothing.

        Implementations SHOULD revoke both the access token and its corresponding
        refresh token, regardless of which of the access token or refresh token is
        provided.

        Args:
            token: The token to revoke.
        """

    async def exchange_token(
        self,
        client: OAuthClientInformationFull,
        params: TokenExchangeParams,
    ) -> OAuthToken:
        """Exchanges a security token for an access token (RFC 8693 token exchange).

        This implements the OAuth 2.0 Token Exchange grant
        (``urn:ietf:params:oauth:grant-type:token-exchange``), which MCP uses to let a
        client present a security token issued by an enterprise identity provider - such
        as the Identity Assertion Authorization Grant (ID-JAG) from SEP-990 - and receive
        an access token for this MCP server. Validating the subject token (signature,
        issuer, audience, expiry, policy) is the responsibility of the implementation.

        The default implementation rejects every request as an unsupported grant type.
        Override it to enable token exchange for this authorization server.

        Args:
            client: The client performing the exchange.
            params: The validated token-exchange request parameters.

        Returns:
            The OAuth token, containing the issued access token. Return a
            ``TokenExchangeToken`` to set RFC 8693's ``issued_token_type``; if a plain
            ``OAuthToken`` is returned, the handler defaults it to the access-token type.

        Raises:
            TokenError: If the subject token or request is invalid. Use ``invalid_target``
                for an unknown or unsupported ``resource``/``audience``.
        """
        raise TokenError(
            error="unsupported_grant_type",
            error_description="Token exchange is not supported by this authorization server",
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
    """Token verifier that uses an OAuthAuthorizationServerProvider.

    This is provided for backwards compatibility with existing auth_server_provider
    configurations. For new implementations using AS/RS separation, consider using
    the TokenVerifier protocol with a dedicated implementation like IntrospectionTokenVerifier.
    """

    def __init__(self, provider: "OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]"):
        self.provider = provider

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token using the provider's load_access_token method."""
        return await self.provider.load_access_token(token)
