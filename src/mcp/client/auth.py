"""
OAuth client implementation for MCP Python SDK.

This module provides an end-to-end OAuth client to be used with MCP servers,
implementing the OAuth 2.0 authorization code flow with PKCE.
"""

import base64
import hashlib
import logging
import secrets
import string
from typing import Literal, Protocol, TypeVar, runtime_checkable
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import httpx

from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)
from mcp.types import LATEST_PROTOCOL_VERSION

# Type variable to represent implementation of OAuthClientProvider
T = TypeVar("T", bound="OAuthClientProvider")

logger = logging.getLogger(__name__)


class UnauthorizedError(Exception):
    """Raised when OAuth authorization fails or is required."""

    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message)
        self.message = message


@runtime_checkable
class OAuthClientProvider(Protocol):
    """
    Protocol for OAuth client providers to be used with MCP servers.

    This provider relies upon a concept of an authorized "session," the exact
    meaning of which is application-defined. Tokens, authorization codes, and
    code verifiers should not cross different sessions.
    """

    @property
    def redirect_url(self) -> str:
        """The URL to redirect the user agent to after authorization."""
        ...

    @property
    def client_metadata(self) -> OAuthClientMetadata:
        """Metadata about this OAuth client."""
        ...

    async def client_information(self) -> OAuthClientInformationFull | None:
        """
        Loads information about this OAuth client, as registered already with the
        server, or returns None if the client is not registered with the server.
        """
        ...

    async def save_client_information(
        self, client_information: OAuthClientInformationFull
    ) -> None:
        """
        If implemented, this permits the OAuth client to dynamically register with
        the server. Client information saved this way should later be read via
        client_information().

        This method is not required to be implemented if client information is
        statically known (e.g., pre-registered).
        """
        ...

    async def tokens(self) -> OAuthToken | None:
        """
        Loads any existing OAuth tokens for the current session, or returns
        None if there are no saved tokens.
        """
        ...

    async def save_tokens(self, tokens: OAuthToken) -> None:
        """
        Stores new OAuth tokens for the current session, after a successful
        authorization.
        """
        ...

    async def redirect_to_authorization(self, authorization_url: str) -> None:
        """
        Invoked to redirect the user agent to the given URL
        to begin the authorization flow.
        """
        ...

    async def save_code_verifier(self, code_verifier: str) -> None:
        """
        Saves a PKCE code verifier for the current session, before redirecting to
        the authorization flow.
        """
        ...

    async def code_verifier(self) -> str:
        """
        Loads the PKCE code verifier for the current session, necessary to validate
        the authorization result.
        """
        ...


class AuthResult:
    """Result of an OAuth authorization attempt."""

    AUTHORIZED = "AUTHORIZED"
    REDIRECT = "REDIRECT"


def _generate_code_verifier() -> str:
    """Generate a cryptographically random code verifier for PKCE."""
    return "".join(
        secrets.choice(string.ascii_letters + string.digits + "-._~")
        for _ in range(128)
    )


def _generate_code_challenge(code_verifier: str) -> str:
    """Generate a code challenge from a code verifier using SHA256."""
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def auth(
    provider: OAuthClientProvider,
    *,
    server_url: str,
    authorization_code: str | None = None,
    scope: str | None = None,
) -> Literal["AUTHORIZED", "REDIRECT"]:
    """
    Orchestrates the full auth flow with a server.

    This can be used as a single entry point for all authorization functionality,
    instead of linking together the other lower-level functions in this module.

    Args:
        provider: OAuth client provider implementation
        server_url: URL of the MCP server
        authorization_code: Optional authorization code from redirect
        scope: Optional scope to request

    Returns:
        AuthResult.AUTHORIZED if successful, AuthResult.REDIRECT if redirect needed

    Raises:
        UnauthorizedError: If authorization fails
    """
    metadata = await discover_oauth_metadata(server_url)

    # Handle client registration if needed
    client_information = await provider.client_information()
    if not client_information:
        if authorization_code is not None:
            raise ValueError(
                "Existing OAuth client information is required "
                "when exchanging an authorization code"
            )

        try:
            save_client_info = provider.save_client_information
        except AttributeError:
            raise ValueError(
                "OAuth client information must be saveable for dynamic registration"
            )

        full_information = await register_client(
            server_url=server_url,
            metadata=metadata,
            client_metadata=provider.client_metadata,
        )
        await save_client_info(full_information)
        client_information = full_information

    # Exchange authorization code for tokens
    if authorization_code is not None:
        code_verifier = await provider.code_verifier()
        tokens = await exchange_authorization(
            server_url=server_url,
            metadata=metadata,
            client_information=client_information,
            authorization_code=authorization_code,
            code_verifier=code_verifier,
            redirect_uri=provider.redirect_url,
        )
        await provider.save_tokens(tokens)
        return AuthResult.AUTHORIZED

    tokens = await provider.tokens()

    # Handle token refresh or new authorization
    if tokens and tokens.refresh_token:
        try:
            # Attempt to refresh the token
            new_tokens = await refresh_authorization(
                server_url=server_url,
                metadata=metadata,
                client_information=client_information,
                refresh_token=tokens.refresh_token,
            )
            await provider.save_tokens(new_tokens)
            return AuthResult.AUTHORIZED
        except Exception as error:
            # Log error but continue to start new authorization flow
            logger.warning(f"Could not refresh OAuth tokens: {error}")

    # Start new authorization flow
    authorization_url, code_verifier = await start_authorization(
        server_url=server_url,
        metadata=metadata,
        client_information=client_information,
        redirect_url=provider.redirect_url,
        scope=scope or provider.client_metadata.scope,
    )

    await provider.save_code_verifier(code_verifier)
    await provider.redirect_to_authorization(authorization_url)
    return AuthResult.REDIRECT


async def discover_oauth_metadata(
    server_url: str,
    protocol_version: str = LATEST_PROTOCOL_VERSION,
) -> OAuthMetadata | None:
    """
    Looks up RFC 8414 OAuth 2.0 Authorization Server Metadata.

    If the server returns a 404 for the well-known endpoint, this function will
    return None. Any other errors will be thrown as exceptions.

    Args:
        server_url: URL of the MCP server
        protocol_version: MCP protocol version header

    Returns:
        OAuth metadata if available, None if not supported
    """
    url = urljoin(server_url, "/.well-known/oauth-authorization-server")

    headers = {"MCP-Protocol-Version": protocol_version}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
        except Exception:
            # Try without MCP protocol version header for CORS issues
            response = await client.get(url)

        if response.status_code == 404:
            return None

        response.raise_for_status()

        try:
            return OAuthMetadata.model_validate(response.json())
        except Exception as e:
            raise ValueError(f"Invalid OAuth metadata: {e}")


async def start_authorization(
    *,
    server_url: str,
    metadata: OAuthMetadata | None,
    client_information: OAuthClientInformationFull,
    redirect_url: str,
    scope: str | None = None,
) -> tuple[str, str]:
    """
    Begins the authorization flow with the given server, by generating a PKCE challenge
    and constructing the authorization URL.

    Args:
        server_url: URL of the MCP server
        metadata: OAuth metadata (optional)
        client_information: OAuth client information
        redirect_url: Redirect URL for authorization
        scope: Optional scope to request

    Returns:
        Tuple of (authorization_url, code_verifier)
    """
    response_type = "code"
    code_challenge_method = "S256"

    if metadata:
        authorization_url = str(metadata.authorization_endpoint)

        if response_type not in metadata.response_types_supported:
            raise ValueError(
                "Incompatible auth server: does not support response type"
                f" {response_type}"
            )

        if (
            metadata.code_challenge_methods_supported is not None
            and code_challenge_method not in metadata.code_challenge_methods_supported
        ):
            raise ValueError(
                "Incompatible auth server: does not support code challenge method "
                f"{code_challenge_method}"
            )
    else:
        authorization_url = urljoin(server_url, "/authorize")

    # Generate PKCE challenge
    code_verifier = _generate_code_verifier()
    code_challenge = _generate_code_challenge(code_verifier)

    # Build authorization URL with parameters
    parsed = urlparse(authorization_url)
    params = {
        "response_type": response_type,
        "client_id": client_information.client_id,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "redirect_uri": redirect_url,
    }

    if scope:
        params["scope"] = scope

    # Construct URL with query parameters
    query = urlencode(params)
    final_url = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            query,
            parsed.fragment,
        )
    )

    return final_url, code_verifier


async def exchange_authorization(
    *,
    server_url: str,
    metadata: OAuthMetadata | None,
    client_information: OAuthClientInformationFull,
    authorization_code: str,
    code_verifier: str,
    redirect_uri: str,
) -> OAuthToken:
    """
    Exchanges an authorization code for an access token with the given server.

    Args:
        server_url: URL of the MCP server
        metadata: OAuth metadata (optional)
        client_information: OAuth client information
        authorization_code: Authorization code from redirect
        code_verifier: PKCE code verifier
        redirect_uri: Redirect URI used in authorization

    Returns:
        OAuth tokens
    """
    grant_type = "authorization_code"

    if metadata:
        token_url = str(metadata.token_endpoint)

        if (
            metadata.grant_types_supported is not None
            and grant_type not in metadata.grant_types_supported
        ):
            raise ValueError(
                f"Incompatible auth server: does not support grant type {grant_type}"
            )
    else:
        token_url = urljoin(server_url, "/token")

    # Exchange code for tokens
    data = {
        "grant_type": grant_type,
        "client_id": client_information.client_id,
        "code": authorization_code,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
    }

    if client_information.client_secret:
        data["client_secret"] = client_information.client_secret

    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if not response.is_success:
            raise Exception(f"Token exchange failed: HTTP {response.status_code}")

        try:
            return OAuthToken.model_validate(response.json())
        except Exception as e:
            raise ValueError(f"Invalid token response: {e}")


async def refresh_authorization(
    *,
    server_url: str,
    metadata: OAuthMetadata | None,
    client_information: OAuthClientInformationFull,
    refresh_token: str,
) -> OAuthToken:
    """
    Exchange a refresh token for an updated access token.

    Args:
        server_url: URL of the MCP server
        metadata: OAuth metadata (optional)
        client_information: OAuth client information
        refresh_token: Refresh token to exchange

    Returns:
        New OAuth tokens
    """
    grant_type = "refresh_token"

    if metadata:
        token_url = str(metadata.token_endpoint)

        if (
            metadata.grant_types_supported is not None
            and grant_type not in metadata.grant_types_supported
        ):
            raise ValueError(
                f"Incompatible auth server: does not support grant type {grant_type}"
            )
    else:
        token_url = urljoin(server_url, "/token")

    # Exchange refresh token
    data = {
        "grant_type": grant_type,
        "client_id": client_information.client_id,
        "refresh_token": refresh_token,
    }

    if client_information.client_secret:
        data["client_secret"] = client_information.client_secret

    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if not response.is_success:
            raise Exception(f"Token refresh failed: HTTP {response.status_code}")

        try:
            return OAuthToken.model_validate(response.json())
        except Exception as e:
            raise ValueError(f"Invalid token response: {e}")


async def register_client(
    *,
    server_url: str,
    metadata: OAuthMetadata | None,
    client_metadata: OAuthClientMetadata,
) -> OAuthClientInformationFull:
    """
    Performs OAuth 2.0 Dynamic Client Registration according to RFC 7591.

    Args:
        server_url: URL of the MCP server
        metadata: OAuth metadata (optional)
        client_metadata: Client metadata for registration

    Returns:
        Full client information after registration
    """
    if metadata:
        if not metadata.registration_endpoint:
            raise ValueError(
                "Incompatible auth server: does not support dynamic client registration"
            )
        registration_url = str(metadata.registration_endpoint)
    else:
        registration_url = urljoin(server_url, "/register")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            registration_url,
            json=client_metadata.model_dump(),
            headers={"Content-Type": "application/json"},
        )

        if not response.is_success:
            raise Exception(
                f"Dynamic client registration failed: HTTP {response.status_code}"
            )

        try:
            return OAuthClientInformationFull.model_validate(response.json())
        except Exception as e:
            raise ValueError(f"Invalid client registration response: {e}")
