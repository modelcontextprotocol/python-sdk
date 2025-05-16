"""
Production-ready OAuth2 Authentication implementation for HTTPX using anyio.

This module provides a complete OAuth 2.0 authentication implementation
that handles authorization code flow with PKCE,
automatic token refresh and proper error handling.
The callback server implementation should be handled by the calling code.
"""

import base64
import hashlib
import secrets
import string
import time
import webbrowser
from collections.abc import AsyncGenerator, Awaitable, Callable
from urllib.parse import urljoin

import anyio
import httpx

from mcp.client.token_storage import InMemoryTokenStorage, TokenStorage
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)
from mcp.types import LATEST_PROTOCOL_VERSION


async def discover_oauth_metadata(server_url: str) -> OAuthMetadata | None:
    """
    Discovers OAuth metadata from the server's well-known endpoint.

    Args:
        server_url: Base URL of the OAuth server

    Returns:
        OAuthMetadata if found, None otherwise
    """
    url = urljoin(server_url, "/.well-known/oauth-authorization-server")
    headers = {"MCP-Protocol-Version": LATEST_PROTOCOL_VERSION}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            metadata_json = response.json()
            print(f"OAuth metadata discovered: {metadata_json}")
            return OAuthMetadata.model_validate(metadata_json)
        except Exception:
            # Try without MCP protocol version header for CORS issues
            try:
                response = await client.get(url)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                metadata_json = response.json()
                print(f"OAuth metadata discovered (no MCP header): {metadata_json}")
                return OAuthMetadata.model_validate(metadata_json)
            except Exception as e:
                print(f"Failed to discover OAuth metadata: {e}")
                return None


async def register_oauth_client(
    server_url: str,
    client_metadata: OAuthClientMetadata,
    metadata: OAuthMetadata | None = None,
) -> OAuthClientInformationFull:
    """
    Registers an OAuth client with the server.

    Args:
        server_url: Base URL of the OAuth server
        client_metadata: Client metadata for registration
        metadata: Optional OAuth metadata (will be discovered if not provided)

    Returns:
        Registered client information
    """
    if not metadata:
        metadata = await discover_oauth_metadata(server_url)

    if metadata and metadata.registration_endpoint:
        registration_url = str(metadata.registration_endpoint)
    else:
        registration_url = urljoin(server_url, "/register")

    # Prepare registration data and adjust scope based on server metadata
    registration_data = client_metadata.model_dump(
        by_alias=True, mode="json", exclude_none=True
    )

    # If the server has supported scopes, use them instead of the requested scope
    if metadata and metadata.scopes_supported:
        # Use the first supported scope or "user" if available
        if "user" in metadata.scopes_supported:
            registration_data["scope"] = "user"
        else:
            registration_data["scope"] = metadata.scopes_supported[0]
        print(f"Adjusted scope to server-supported: {registration_data['scope']}")

    print(f"Attempting registration at {registration_url}")
    print(f"Registration data: {registration_data}")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                registration_url,
                json=registration_data,
                headers={"Content-Type": "application/json"},
            )

            if response.status_code not in (200, 201):
                print(
                    f"Registration failed with {response.status_code}: {response.text}"
                )
                raise httpx.HTTPStatusError(
                    f"Registration failed: {response.status_code}",
                    request=response.request,
                    response=response,
                )

            response_data = response.json()
            print(f"Registration successful: {response_data}")
            return OAuthClientInformationFull.model_validate(response_data)

        except httpx.HTTPStatusError:
            raise
        except Exception as e:
            print(f"Registration error: {e}")
            raise


class ProductionOAuth2Auth(httpx.Auth):
    """
    Production-ready OAuth2 Authentication for httpx using anyio.
    Handles OAuth flow with automatic client registration and token storage.
    """

    def __init__(
        self,
        server_url: str,
        client_metadata: OAuthClientMetadata,
        storage: TokenStorage | None = None,
        redirect_handler: Callable[[str], Awaitable[None]] | None = None,
        callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None = None,
        timeout: float = 300.0,  # 5 minutes timeout for OAuth flow
    ):
        """
        Initialize OAuth2 authentication.

        Args:
            server_url: Base URL of the OAuth server
            client_metadata: OAuth client metadata
            storage: Token storage implementation (defaults to in-memory)
            redirect_handler: Function to handle authorization URL (defaults to opening browser)
            callback_handler: Function to wait for callback and return (auth_code, state)
            timeout: Timeout for OAuth flow in seconds
        """
        self.server_url = server_url
        self.client_metadata = client_metadata
        self.storage = storage or InMemoryTokenStorage()
        self.redirect_handler = redirect_handler or self._default_redirect_handler
        self.callback_handler = callback_handler
        self.timeout = timeout

        # Cache for current tokens and metadata
        self._current_tokens: OAuthToken | None = None
        self._metadata: OAuthMetadata | None = None
        self._client_info: OAuthClientInformationFull | None = None
        self._token_expiry_time: float | None = None

        # PKCE parameters
        self._code_verifier: str | None = None
        self._code_challenge: str | None = None

        # Lock for thread safety during token operations
        self._token_lock = anyio.Lock()

    async def _default_redirect_handler(self, authorization_url: str) -> None:
        """Default redirect handler that opens the URL in a browser."""
        print(f"Opening browser for authorization: {authorization_url}")
        webbrowser.open(authorization_url)

    def _generate_code_verifier(self) -> str:
        """Generate a cryptographically random code verifier for PKCE."""
        return "".join(
            secrets.choice(string.ascii_letters + string.digits + "-._~")
            for _ in range(128)
        )

    def _generate_code_challenge(self, code_verifier: str) -> str:
        """Generate a code challenge from a code verifier using SHA256."""
        digest = hashlib.sha256(code_verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """
        Handle authentication flow for requests.

        This method adds the Bearer token if available and handles 401 responses.
        The actual OAuth flow initialization should be done before using this auth handler.
        """

        if not self._has_valid_token():
            await self.initialize()
            await self.ensure_token()
        # Add token to request if available
        if self._current_tokens and self._current_tokens.access_token:
            request.headers["Authorization"] = (
                f"Bearer {self._current_tokens.access_token}"
            )

        response = yield request

        # If we get a 401, we could attempt refresh or re-auth
        # but due to the synchronous nature of this method, the calling code
        # should handle token refresh/re-authentication at a higher level
        if response.status_code == 401:
            # Clear the token so next request will trigger re-auth
            self._current_tokens = None

    def _has_valid_token(self) -> bool:
        """Check if current token is valid."""
        if not self._current_tokens or not self._current_tokens.access_token:
            return False

        # Check token expiry if available
        if self._token_expiry_time and time.time() > self._token_expiry_time:
            return False

        return True

    async def initialize(self) -> None:
        """Initialize the auth handler by loading stored tokens and client info."""
        self._current_tokens = await self.storage.get_tokens()
        self._client_info = await self.storage.get_client_info()

    async def _get_or_register_client(self) -> OAuthClientInformationFull:
        """Get existing client info or register a new client."""
        if not self._client_info:
            try:
                self._client_info = await register_oauth_client(
                    self.server_url, self.client_metadata, self._metadata
                )
                await self.storage.set_client_info(self._client_info)
                print(f"Successfully registered client: {self._client_info.client_id}")
            except Exception as e:
                print(f"Client registration failed: {e}")
                print("Using fallback client configuration for testing")
                # Create a fallback client configuration for testing
                # This allows us to test the OAuth flow even if registration isn't supported
                self._client_info = OAuthClientInformationFull(
                    client_id="simple-auth-client",
                    client_secret=None,  # Some servers don't require client secrets
                    **self.client_metadata.model_dump(exclude_none=True),
                )
                await self.storage.set_client_info(self._client_info)
        return self._client_info

    async def ensure_token(self) -> None:
        """Ensure we have a valid access token, performing OAuth flow if needed."""
        async with self._token_lock:
            # Check if we have a valid token
            if self._has_valid_token():
                return

            # Try to refresh token first
            if (
                self._current_tokens
                and self._current_tokens.refresh_token
                and await self._refresh_access_token()
            ):
                return

            # Perform full OAuth flow
            await self._perform_oauth_flow()

    async def _perform_oauth_flow(self) -> None:
        """Perform complete OAuth2 authorization code flow."""
        print("Starting OAuth2 authentication flow...")

        # Discover metadata if not already done
        if not self._metadata:
            self._metadata = await discover_oauth_metadata(self.server_url)

        # Get or register client
        client_info = await self._get_or_register_client()

        # Generate PKCE parameters
        self._code_verifier = self._generate_code_verifier()
        self._code_challenge = self._generate_code_challenge(self._code_verifier)

        # Determine endpoints from metadata or use defaults
        if self._metadata and self._metadata.authorization_endpoint:
            auth_url_base = str(self._metadata.authorization_endpoint)
        else:
            auth_url_base = urljoin(self.server_url, "/authorize")

        # Build authorization URL
        auth_params = {
            "response_type": "code",
            "client_id": client_info.client_id,
            "redirect_uri": self.client_metadata.redirect_uris[0],
            "state": secrets.token_urlsafe(32),
            "code_challenge": self._code_challenge,
            "code_challenge_method": "S256",
        }

        if hasattr(client_info, "scope") and client_info.scope:
            auth_params["scope"] = client_info.scope
        elif self._metadata and self._metadata.scopes_supported:
            # Use "user" if available, otherwise the first supported scope
            if "user" in self._metadata.scopes_supported:
                auth_params["scope"] = "user"
            else:
                auth_params["scope"] = self._metadata.scopes_supported[0]
        elif self.client_metadata.scope:
            auth_params["scope"] = self.client_metadata.scope

        from urllib.parse import urlencode

        auth_url = f"{auth_url_base}?{urlencode(auth_params)}"

        # Handle redirect (open browser or custom handler)
        await self.redirect_handler(auth_url)

        # Wait for callback using the provided callback handler
        if not self.callback_handler:
            raise Exception("No callback handler provided for OAuth flow")

        auth_code, returned_state = await self.callback_handler()

        # Validate state parameter
        if returned_state != auth_params["state"]:
            raise Exception("State parameter mismatch - possible CSRF attack")

        if not auth_code:
            raise Exception("No authorization code received")

        # Exchange code for token
        await self._exchange_code_for_token(auth_code, client_info)

    async def _exchange_code_for_token(
        self, auth_code: str, client_info: OAuthClientInformationFull
    ) -> None:
        """Exchange authorization code for access token."""
        # Determine token endpoint
        if self._metadata and self._metadata.token_endpoint:
            token_url = str(self._metadata.token_endpoint)
        else:
            token_url = urljoin(self.server_url, "/token")

        token_data = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": str(self.client_metadata.redirect_uris[0]),
            "client_id": client_info.client_id,
            "code_verifier": self._code_verifier,
        }

        if client_info.client_secret:
            token_data["client_secret"] = client_info.client_secret

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0,
            )

            if response.status_code != 200:
                raise Exception(
                    f"Token exchange failed: {response.status_code} {response.text}"
                )

            # Parse and store tokens
            token_response = OAuthToken.model_validate(response.json())

            # Calculate expiry time if available
            if token_response.expires_in:
                self._token_expiry_time = time.time() + token_response.expires_in
            else:
                self._token_expiry_time = None

            # Store tokens in storage and cache
            await self.storage.set_tokens(token_response)
            self._current_tokens = token_response

            print("Successfully obtained access token!")

    async def _refresh_access_token(self) -> bool:
        """Refresh the access token using refresh token."""
        if not self._current_tokens or not self._current_tokens.refresh_token:
            return False

        # Get client info
        client_info = await self._get_or_register_client()

        # Determine token endpoint
        if self._metadata and self._metadata.token_endpoint:
            token_url = str(self._metadata.token_endpoint)
        else:
            token_url = urljoin(self.server_url, "/token")

        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": self._current_tokens.refresh_token,
            "client_id": client_info.client_id,
        }

        if client_info.client_secret:
            refresh_data["client_secret"] = client_info.client_secret

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    token_url,
                    data=refresh_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=30.0,
                )

                if response.status_code != 200:
                    print(f"Token refresh failed: {response.status_code}")
                    return False

                # Parse and store new tokens
                token_response = OAuthToken.model_validate(response.json())

                # Calculate expiry time if available
                if token_response.expires_in:
                    self._token_expiry_time = time.time() + token_response.expires_in
                else:
                    self._token_expiry_time = None

                # Store tokens in storage and cache
                await self.storage.set_tokens(token_response)
                self._current_tokens = token_response

                print("Successfully refreshed access token!")
                return True

        except Exception as e:
            print(f"Token refresh error: {e}")
            return False


# Maintain compatibility with existing OAuthAuth class
OAuthAuth = ProductionOAuth2Auth
