"""
OAuth2 Authentication implementation for HTTPX.

Implements authorization code flow with PKCE and automatic token refresh.
"""

import base64
import hashlib
import logging
import secrets
import string
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Protocol
from urllib.parse import urlencode, urljoin

import anyio
import httpx

from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthMetadata, OAuthToken
from mcp.types import LATEST_PROTOCOL_VERSION

logger = logging.getLogger(__name__)


class TokenStorage(Protocol):
    """Protocol for token storage implementations."""

    async def get_tokens(self) -> OAuthToken | None:
        """Get stored tokens."""
        ...

    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Store tokens."""
        ...

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        """Get stored client information."""
        ...

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Store client information."""
        ...


class OAuthClientProvider(httpx.Auth):
    """
    Authentication for httpx using anyio.
    Handles OAuth flow with automatic client registration and token storage.
    """

    def __init__(
        self,
        server_url: str,
        client_metadata: OAuthClientMetadata,
        storage: TokenStorage,
        redirect_handler: Callable[[str], Awaitable[None]],
        callback_handler: Callable[[], Awaitable[tuple[str, str | None]]],
        timeout: float = 300.0,
    ):
        """
        Initialize OAuth2 authentication.

        Args:
            server_url: Base URL of the OAuth server
            client_metadata: OAuth client metadata
            storage: Token storage implementation (defaults to in-memory)
            redirect_handler: Function to handle authorization URL like opening browser
            callback_handler: Function to wait for callback
                              and return (auth_code, state)
            timeout: Timeout for OAuth flow in seconds
        """
        self.server_url = server_url
        self.client_metadata = client_metadata
        self.storage = storage
        self.redirect_handler = redirect_handler
        self.callback_handler = callback_handler
        self.timeout = timeout

        # Cached authentication state
        self._current_tokens: OAuthToken | None = None
        self._metadata: OAuthMetadata | None = None
        self._client_info: OAuthClientInformationFull | None = None
        self._token_expiry_time: float | None = None

        # PKCE flow parameters
        self._code_verifier: str | None = None
        self._code_challenge: str | None = None

        # State parameter for CSRF protection
        self._auth_state: str | None = None

        # Thread safety lock
        self._token_lock = anyio.Lock()

    def _generate_code_verifier(self) -> str:
        """Generate a cryptographically random code verifier for PKCE."""
        return "".join(secrets.choice(string.ascii_letters + string.digits + "-._~") for _ in range(128))

    def _generate_code_challenge(self, code_verifier: str) -> str:
        """Generate a code challenge from a code verifier using SHA256."""
        digest = hashlib.sha256(code_verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def _get_authorization_base_url(self, server_url: str) -> str:
        """
        Extract base URL by removing path component.

        Per MCP spec 2.3.2: https://api.example.com/v1/mcp -> https://api.example.com
        """
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(server_url)
        # Remove path component
        return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))

    async def _discover_oauth_metadata(self, server_url: str) -> OAuthMetadata | None:
        """
        Discover OAuth metadata from server's well-known endpoint.
        """
        # Extract base URL per MCP spec
        auth_base_url = self._get_authorization_base_url(server_url)
        url = urljoin(auth_base_url, "/.well-known/oauth-authorization-server")
        headers = {"MCP-Protocol-Version": LATEST_PROTOCOL_VERSION}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                metadata_json = response.json()
                logger.debug(f"OAuth metadata discovered: {metadata_json}")
                return OAuthMetadata.model_validate(metadata_json)
            except Exception:
                # Retry without MCP header for CORS compatibility
                try:
                    response = await client.get(url)
                    if response.status_code == 404:
                        return None
                    response.raise_for_status()
                    metadata_json = response.json()
                    logger.debug(f"OAuth metadata discovered (no MCP header): {metadata_json}")
                    return OAuthMetadata.model_validate(metadata_json)
                except Exception:
                    logger.exception("Failed to discover OAuth metadata")
                    return None

    async def _register_oauth_client(
        self,
        server_url: str,
        client_metadata: OAuthClientMetadata,
        metadata: OAuthMetadata | None = None,
    ) -> OAuthClientInformationFull:
        """
        Register OAuth client with server.
        """
        if not metadata:
            metadata = await self._discover_oauth_metadata(server_url)

        if metadata and metadata.registration_endpoint:
            registration_url = str(metadata.registration_endpoint)
        else:
            # Use fallback registration endpoint
            auth_base_url = self._get_authorization_base_url(server_url)
            registration_url = urljoin(auth_base_url, "/register")

        # Handle default scope
        if client_metadata.scope is None and metadata and metadata.scopes_supported is not None:
            client_metadata.scope = " ".join(metadata.scopes_supported)

        # Serialize client metadata
        registration_data = client_metadata.model_dump(by_alias=True, mode="json", exclude_none=True)

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    registration_url,
                    json=registration_data,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code not in (200, 201):
                    raise httpx.HTTPStatusError(
                        f"Registration failed: {response.status_code}",
                        request=response.request,
                        response=response,
                    )

                response_data = response.json()
                logger.debug(f"Registration successful: {response_data}")
                return OAuthClientInformationFull.model_validate(response_data)

            except httpx.HTTPStatusError:
                raise
            except Exception:
                logger.exception("Registration error")
                raise

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """
        HTTPX auth flow integration.
        """

        if not self._has_valid_token():
            await self.initialize()
            await self.ensure_token()
        # Add Bearer token if available
        if self._current_tokens and self._current_tokens.access_token:
            request.headers["Authorization"] = f"Bearer {self._current_tokens.access_token}"

        response = yield request

        # Clear token on 401 to trigger re-auth
        if response.status_code == 401:
            self._current_tokens = None

    def _has_valid_token(self) -> bool:
        """Check if current token is valid."""
        if not self._current_tokens or not self._current_tokens.access_token:
            return False

        # Check expiry time
        if self._token_expiry_time and time.time() > self._token_expiry_time:
            return False

        return True

    async def _validate_token_scopes(self, token_response: OAuthToken) -> None:
        """
        Validate returned scopes against requested scopes.

        Per OAuth 2.1 Section 3.3: server may grant subset, not superset.
        """
        if not token_response.scope:
            # No scope returned = validation passes
            return

        # Check explicitly requested scopes only
        requested_scopes: set[str] = set()

        if self.client_metadata.scope:
            # Validate against explicit scope request
            requested_scopes = set(self.client_metadata.scope.split())

            # Check for unauthorized scopes
            returned_scopes = set(token_response.scope.split())
            unauthorized_scopes = returned_scopes - requested_scopes

            if unauthorized_scopes:
                raise Exception(
                    f"Server granted unauthorized scopes: {unauthorized_scopes}. "
                    f"Requested: {requested_scopes}, Returned: {returned_scopes}"
                )
        else:
            # No explicit scopes requested - accept server defaults
            logger.debug(
                f"No explicit scopes requested, accepting server-granted "
                f"scopes: {set(token_response.scope.split())}"
            )

    async def initialize(self) -> None:
        """Load stored tokens and client info."""
        self._current_tokens = await self.storage.get_tokens()
        self._client_info = await self.storage.get_client_info()

    async def _get_or_register_client(self) -> OAuthClientInformationFull:
        """Get or register client with server."""
        if not self._client_info:
            try:
                self._client_info = await self._register_oauth_client(
                    self.server_url, self.client_metadata, self._metadata
                )
                await self.storage.set_client_info(self._client_info)
            except Exception:
                logger.exception("Client registration failed")
                raise
        return self._client_info

    async def ensure_token(self) -> None:
        """Ensure valid access token, refreshing or re-authenticating as needed."""
        async with self._token_lock:
            # Return early if token is valid
            if self._has_valid_token():
                return

            # Try refreshing existing token
            if self._current_tokens and self._current_tokens.refresh_token and await self._refresh_access_token():
                return

            # Fall back to full OAuth flow
            await self._perform_oauth_flow()

    async def _perform_oauth_flow(self) -> None:
        """Execute OAuth2 authorization code flow with PKCE."""
        logger.debug("Starting authentication flow.")

        # Discover OAuth metadata
        if not self._metadata:
            self._metadata = await self._discover_oauth_metadata(self.server_url)

        # Ensure client registration
        client_info = await self._get_or_register_client()

        # Generate PKCE challenge
        self._code_verifier = self._generate_code_verifier()
        self._code_challenge = self._generate_code_challenge(self._code_verifier)

        # Get authorization endpoint
        if self._metadata and self._metadata.authorization_endpoint:
            auth_url_base = str(self._metadata.authorization_endpoint)
        else:
            # Use fallback authorization endpoint
            auth_base_url = self._get_authorization_base_url(self.server_url)
            auth_url_base = urljoin(auth_base_url, "/authorize")

        # Build authorization URL
        self._auth_state = secrets.token_urlsafe(32)
        auth_params = {
            "response_type": "code",
            "client_id": client_info.client_id,
            "redirect_uri": str(self.client_metadata.redirect_uris[0]),
            "state": self._auth_state,
            "code_challenge": self._code_challenge,
            "code_challenge_method": "S256",
        }

        # Include explicit scopes only
        if self.client_metadata.scope:
            auth_params["scope"] = self.client_metadata.scope

        auth_url = f"{auth_url_base}?{urlencode(auth_params)}"

        # Redirect user for authorization
        await self.redirect_handler(auth_url)

        auth_code, returned_state = await self.callback_handler()

        # Validate state parameter for CSRF protection
        if returned_state is None or not secrets.compare_digest(returned_state, self._auth_state):
            raise Exception(f"State parameter mismatch: {returned_state} != {self._auth_state}")

        # Clear state after validation
        self._auth_state = None

        if not auth_code:
            raise Exception("No authorization code received")

        # Exchange authorization code for tokens
        await self._exchange_code_for_token(auth_code, client_info)

    async def _exchange_code_for_token(self, auth_code: str, client_info: OAuthClientInformationFull) -> None:
        """Exchange authorization code for access token."""
        # Get token endpoint
        if self._metadata and self._metadata.token_endpoint:
            token_url = str(self._metadata.token_endpoint)
        else:
            # Use fallback token endpoint
            auth_base_url = self._get_authorization_base_url(self.server_url)
            token_url = urljoin(auth_base_url, "/token")

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
                # Parse OAuth error response
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error_description", error_data.get("error", "Unknown error"))
                    raise Exception(f"Token exchange failed: {error_msg} " f"(HTTP {response.status_code})")
                except Exception:
                    raise Exception(f"Token exchange failed: {response.status_code} {response.text}")

            # Parse token response
            token_response = OAuthToken.model_validate(response.json())

            # Validate token scopes
            await self._validate_token_scopes(token_response)

            # Calculate token expiry
            if token_response.expires_in:
                self._token_expiry_time = time.time() + token_response.expires_in
            else:
                self._token_expiry_time = None

            # Store tokens
            await self.storage.set_tokens(token_response)
            self._current_tokens = token_response

    async def _refresh_access_token(self) -> bool:
        """Refresh access token using refresh token."""
        if not self._current_tokens or not self._current_tokens.refresh_token:
            return False

        # Get client credentials
        client_info = await self._get_or_register_client()

        # Get token endpoint
        if self._metadata and self._metadata.token_endpoint:
            token_url = str(self._metadata.token_endpoint)
        else:
            # Use fallback token endpoint
            auth_base_url = self._get_authorization_base_url(self.server_url)
            token_url = urljoin(auth_base_url, "/token")

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
                    logger.error(f"Token refresh failed: {response.status_code}")
                    return False

                # Parse refreshed tokens
                token_response = OAuthToken.model_validate(response.json())

                # Validate token scopes
                await self._validate_token_scopes(token_response)

                # Calculate token expiry
                if token_response.expires_in:
                    self._token_expiry_time = time.time() + token_response.expires_in
                else:
                    self._token_expiry_time = None

                # Store refreshed tokens
                await self.storage.set_tokens(token_response)
                self._current_tokens = token_response

                return True

        except Exception:
            logger.exception("Token refresh failed")
            return False
