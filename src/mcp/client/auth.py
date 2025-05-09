"""
OAuth 2.0 Client Implementation

This module provides a complete OAuth 2.0 client implementation supporting:
- Authorization Code Flow with PKCE
- Dynamic Client Registration
- Token Refresh
- OAuth Server Metadata Discovery
"""

from typing import Protocol, cast
from urllib.parse import urlencode, urljoin

import httpx
from pkce import generate_pkce_pair  # type: ignore

from mcp.shared.auth import (
    OAuthClientInformation,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)
from mcp.types import LATEST_PROTOCOL_VERSION


class OAuthClientProvider(Protocol):
    """Protocol defining the interface for OAuth client providers."""

    def get_redirect_url(self) -> str:
        """Get the URL where the user agent will be redirected after authorization."""
        ...

    def get_client_metadata(self) -> OAuthClientMetadata:
        """Get the metadata for this OAuth client."""
        ...

    def get_client_information(self) -> OAuthClientInformation | None:
        """Get the client information as registered with the server.

        Returns None if the client is not registered.
        """
        ...

    def save_client_information(self, client_information: OAuthClientInformationFull):
        """Optional Function to save the client information received from the server.

        If implemented, this provider will support dynamic client registration.
        """
        ...

    def get_token(self) -> OAuthToken | None:
        """Get any existing OAuth tokens for the current session."""
        ...

    def save_token(self, token: OAuthToken):
        """Save the new OAuth token after successful authorization."""
        ...

    def redirect_to_authorization(self, authorization_url: str):
        """Redirect the user agent to begin the authorization flow."""
        ...

    def get_code_verifier(self) -> str:
        """Get the PKCE code verifier for the current session."""
        ...

    def save_code_verifier(self, pkce_code_verifier: str):
        """Save the PKCE code verifier before redirecting to authorization."""
        ...


class OAuthAuthorization:
    """Main class for handling OAuth 2.0 authorization flows.

    This class implements the OAuth 2.0 Authorization Code Flow with PKCE,
    supporting dynamic client registration and token refresh.
    """

    def __init__(self, provider: OAuthClientProvider, server_url: str):
        """Initialize the OAuth authorization handler.

        Args:
            provider: The OAuth client provider implementation
            server_url: The base URL of the OAuth server
        """
        self.provider = provider
        self.server_url = server_url

    async def authorize(
        self, authorization_code: str | None = None
    ) -> OAuthToken | None:
        """Main authorization method that handles the complete OAuth flow.

        This method will:
        1. Check for existing valid tokens
        2. Refresh tokens if expired
        3. Exchange authorization codes for tokens
        4. Start new authorization flows if needed

        Args:
            authorization_code: Optional authorization code from the server

        Returns:
            OAuthToken if authorization is successful, None if redirect is needed
        """
        token = self.provider.get_token()
        if token is not None:
            # Returned token is still valid so return the token
            if token.expires_in is None or token.expires_in > 0:
                return token
            elif token.refresh_token is not None:
                # Refresh token
                refreshed_token = await self.refresh_authorization(token.refresh_token)
                self.provider.save_token(refreshed_token)
                return refreshed_token

        # If we have authorization code, exchange it for an access token
        if authorization_code:
            token = await self.exchange_authorization(authorization_code)
            self.provider.save_token(token)
            return token

        # If no authorization code, build authorization url and redirect
        authorization_url, code_verifier = await self.start_authorization()
        self.provider.save_code_verifier(code_verifier)
        self.provider.redirect_to_authorization(authorization_url)
        return None

    async def start_authorization(self) -> tuple[str, str]:
        """Start a new authorization flow by generating PKCE values and
           building the authorization URL.

        Returns:
            Tuple containing:
            - The complete authorization URL to redirect the user to
            - The PKCE code verifier to be used later in token exchange
        """
        metadata = await self.discover_oauth_metadata()
        client_info = await self.get_client_information()

        response_type = "code"
        code_challenge_method = "S256"

        if metadata is not None:
            if (
                metadata.response_types_supported
                and response_type not in metadata.response_types_supported
            ):
                raise ValueError(
                    f"Incompatible auth server: {response_type} response type "
                    "is not supported"
                )
            if metadata.code_challenge_methods_supported is None or (
                code_challenge_method not in metadata.code_challenge_methods_supported
            ):
                raise ValueError(
                    f"Incompatible auth server: {code_challenge_method} code "
                    "challenge method is not supported"
                )
            authorization_url = str(metadata.authorization_endpoint)
        else:
            authorization_url = urljoin(self.server_url, "/authorize")

        code_verifier, code_challenge = cast(tuple[str, str], generate_pkce_pair())
        params: dict[str, str] = {
            "response_type": response_type,
            "client_id": client_info.client_id,
            "redirect_uri": self.provider.get_redirect_url(),
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        }
        query_string = urlencode(params)
        return (f"{authorization_url}?{query_string}", code_verifier)

    async def discover_oauth_metadata(self) -> OAuthMetadata | None:
        """Discover OAuth server metadata using the well-known endpoint.

        Implements RFC 8414 OAuth 2.0 Authorization Server Metadata.

        Returns:
            OAuthMetadata if discovery is successful, None if endpoint returns 404
        """
        url = urljoin(self.server_url, "/.well-known/openid-configuration")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers={"MCP-Protocol-Version": LATEST_PROTOCOL_VERSION}
            )
            if resp.status_code == 404:
                return None
            elif resp.status_code != 200:
                raise ValueError(
                    f"Failed to discover OAuth metadata: HTTP {resp.status_code} "
                    f"{resp.text}"
                )
            return OAuthMetadata(**resp.json())

    async def register_client(
        self,
        metadata: OAuthMetadata | None,
        client_metadata: OAuthClientMetadata,
    ) -> OAuthClientInformationFull:
        """Register the client with the OAuth server.

        Implements OAuth 2.0 Dynamic Client Registration (RFC 7591).

        Args:
            metadata: Optional OAuth server metadata
            client_metadata: The client's metadata to register

        Returns:
            Full client information from the server
        """
        url = (
            str(metadata.registration_endpoint)
            if metadata
            else urljoin(self.server_url, "/register")
        )

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                json=client_metadata.model_dump(),
            )
            if resp.status_code != 200:
                raise ValueError(
                    f"Dynamic client registration failed: HTTP {resp.status_code} "
                    f"{resp.text}"
                )
            return OAuthClientInformationFull(**resp.json())

    async def get_client_information(self) -> OAuthClientInformation:
        """Tries to get the client information from the provider.

        If unable to retrieve the client information, this attempts
        dynamic registration, saves the client with the provider
        and returns the information.

        Returns:
            Client information
        """
        client_info = self.provider.get_client_information()

        if client_info is None:
            if not hasattr(self.provider, "save_client_information"):
                raise ValueError(
                    "Save Client Information is not supported by this provider, "
                    "therefore we cannot dynamically register the OAuth Client"
                )

            client_info = await self.register_client(
                metadata=None, client_metadata=self.provider.get_client_metadata()
            )
            self.provider.save_client_information(client_info)
            return OAuthClientInformation(**client_info.model_dump())

        return client_info

    async def exchange_authorization(self, authorization_code: str) -> OAuthToken:
        """Exchange an authorization code for an access token.

        Args:
            authorization_code: The authorization code from the server

        Returns:
            New OAuth token
        """
        code_verifier = self.provider.get_code_verifier()
        redirect_url = self.provider.get_redirect_url()

        return await self._fetch_token(
            grant_type="authorization_code",
            extra_params={
                "code": authorization_code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_url,
            },
        )

    async def refresh_authorization(self, refresh_token: str) -> OAuthToken:
        """Exchange a refresh token for a new access token.

        Args:
            refresh_token: The refresh token to use

        Returns:
            New OAuth token
        """
        return await self._fetch_token(
            grant_type="refresh_token",
            extra_params={
                "refresh_token": refresh_token,
            },
        )

    async def _fetch_token(
        self,
        grant_type: str,
        extra_params: dict[str, str],
    ) -> OAuthToken:
        """Internal method to fetch tokens from the server.

        Handles both authorization code exchange and token refresh.

        Args:
            grant_type: The OAuth grant type to use
            extra_params: Additional parameters for the token request

        Returns:
            New OAuth token
        """
        metadata = await self.discover_oauth_metadata()
        if metadata is not None:
            token_url = str(metadata.token_endpoint)
            if (
                metadata.grant_types_supported
                and grant_type not in metadata.grant_types_supported
            ):
                raise ValueError(
                    f"Incompatible auth server: {grant_type} not supported"
                )
        else:
            token_url = urljoin(self.server_url, "/token")

        client_info = await self.get_client_information()
        params: dict[str, str] = {
            "grant_type": grant_type,
            "client_id": client_info.client_id,
            **extra_params,
        }
        if client_info.client_secret:
            params["client_secret"] = client_info.client_secret

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                token_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                json=params,
            )
            if resp.status_code != 200:
                raise ValueError(
                    f"Token request failed for {grant_type}: "
                    f"HTTP {resp.status_code} {resp.text}"
                )
            return OAuthToken(**resp.json())
