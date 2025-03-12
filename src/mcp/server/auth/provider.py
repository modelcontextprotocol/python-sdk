from typing import Protocol
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from pydantic import AnyHttpUrl, BaseModel

from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthToken,
)


class AuthorizationParams(BaseModel):
    state: str | None = None
    scopes: list[str] | None = None
    code_challenge: str
    redirect_uri: AnyHttpUrl


class AuthorizationCode(BaseModel):
    code: str
    scopes: list[str]
    expires_at: float
    client_id: str
    code_challenge: str
    redirect_uri: AnyHttpUrl


class RefreshToken(BaseModel):
    token: str
    client_id: str
    scopes: list[str]
    expires_at: int | None = None


class AuthInfo(BaseModel):
    token: str
    client_id: str
    scopes: list[str]
    expires_at: int | None = None


class OAuthRegisteredClientsStore(Protocol):
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """
        Retrieves client information by client ID.

        Args:
            client_id: The ID of the client to retrieve.

        Returns:
            The client information, or None if the client does not exist.
        """
        ...

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """
        Saves client information as part of registering it.

        Args:
            client_info: The client metadata to register.
        """
        ...


class OAuthServerProvider(Protocol):
    @property
    def clients_store(self) -> OAuthRegisteredClientsStore:
        """
        A store used to read information about registered OAuth clients.
        """
        ...

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """
        Called as part of the /authorize endpoint, and returns a URL that the client
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

        Implementations will need to define another handler on the MCP server return
        flow to perform the second redirect, and generates and stores an authorization
        code as part of completing the OAuth authorization step.

        Implementations SHOULD generate an authorization code with at least 160 bits of
        entropy,
        and MUST generate an authorization code with at least 128 bits of entropy.
        See https://datatracker.ietf.org/doc/html/rfc6749#section-10.10.
        """
        ...

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        """
        Loads metadata for the authorization code challenge.

        Args:
            client: The client that requested the authorization code.
            authorization_code: The authorization code to get the challenge for.

        Returns:
            The code challenge that was used when the authorization began.
        """
        ...

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """
        Exchanges an authorization code for an access token.

        Args:
            client: The client exchanging the authorization code.
            authorization_code: The authorization code to exchange.

        Returns:
            The access and refresh tokens.
        """
        ...

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None: ...

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """
        Exchanges a refresh token for an access token.

        Args:
            client: The client exchanging the refresh token.
            refresh_token: The refresh token to exchange.
            scopes: Optional scopes to request with the new access token.

        Returns:
            The new access and refresh tokens.
        """
        ...

    async def load_access_token(self, token: str) -> AuthInfo | None:
        """
        Verifies an access token and returns information about it.

        Args:
            token: The access token to verify.

        Returns:
            Information about the verified token, or None if the token is invalid.
        """
        ...

    async def revoke_token(
        self,
        token: AuthInfo | RefreshToken,
    ) -> None:
        """
        Revokes an access or refresh token.

        If the given token is invalid or already revoked, this method should do nothing.

        Args:
            token: the token to revoke
            token_type_hint: hint about the type of token to revoke; optional. if the
            token cannot be located using this hint, the provider MUST extend its search
            to include all tokens.
        """
        ...


def construct_redirect_uri(redirect_uri_base: str, **params: str | None) -> str:
    parsed_uri = urlparse(redirect_uri_base)
    query_params = [(k, v) for k, vs in parse_qs(parsed_uri.query) for v in vs]
    for k, v in params.items():
        if v is not None:
            query_params.append((k, v))

    redirect_uri = urlunparse(parsed_uri._replace(query=urlencode(query_params)))
    return redirect_uri
