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
from dataclasses import dataclass, field
from typing import Optional, Protocol
from urllib.parse import urlencode, urljoin, urlparse

import anyio
import httpx
from pydantic import BaseModel, Field, ValidationError

from mcp.client.streamable_http import MCP_PROTOCOL_VERSION
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)
from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url
from mcp.types import LATEST_PROTOCOL_VERSION

logger = logging.getLogger(__name__)


class OAuthFlowError(Exception):
    """Base exception for OAuth flow errors."""


class OAuthTokenError(OAuthFlowError):
    """Raised when token operations fail."""


class OAuthRegistrationError(OAuthFlowError):
    """Raised when client registration fails."""


class PKCEParameters(BaseModel):
    """PKCE (Proof Key for Code Exchange) parameters."""

    code_verifier: str = Field(..., min_length=43, max_length=128)
    code_challenge: str = Field(..., min_length=43, max_length=128)

    @classmethod
    def generate(cls) -> "PKCEParameters":
        """Generate new PKCE parameters."""
        code_verifier = "".join(secrets.choice(string.ascii_letters + string.digits + "-._~") for _ in range(128))
        digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        return cls(code_verifier=code_verifier, code_challenge=code_challenge)


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


@dataclass
class OAuthContext:
    """OAuth flow context."""

    server_url: str
    client_metadata: OAuthClientMetadata
    storage: TokenStorage
    redirect_handler: Optional[Callable[[str], Awaitable[None]]]
    callback_handler: Optional[Callable[[], Awaitable[tuple[str, str | None]]]]
    timeout: float = 300.0

    # Discovered metadata
    protected_resource_metadata: ProtectedResourceMetadata | None = None
    oauth_metadata: OAuthMetadata | None = None
    auth_server_url: str | None = None

    # Client registration
    client_info: OAuthClientInformationFull | None = None

    # Token management
    current_tokens: OAuthToken | None = None
    token_expiry_time: float | None = None

    # State
    lock: anyio.Lock = field(default_factory=anyio.Lock)

    def get_authorization_base_url(self, server_url: str) -> str:
        """Extract base URL by removing path component."""
        parsed = urlparse(server_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def update_token_expiry(self, token: OAuthToken) -> None:
        """Update token expiry time."""
        if token.expires_in:
            self.token_expiry_time = time.time() + token.expires_in
        else:
            self.token_expiry_time = None

    def is_token_valid(self) -> bool:
        """Check if current token is valid."""
        return bool(
            self.current_tokens
            and self.current_tokens.access_token
            and (not self.token_expiry_time or time.time() <= self.token_expiry_time)
        )

    def can_refresh_token(self) -> bool:
        """Check if token can be refreshed."""
        return bool(self.current_tokens and self.current_tokens.refresh_token and self.client_info)

    def clear_tokens(self) -> None:
        """Clear current tokens."""
        self.current_tokens = None
        self.token_expiry_time = None

    def get_resource_url(self) -> str:
        """Get resource URL for RFC 8707.

        Uses PRM resource if it's a valid parent, otherwise uses canonical server URL.
        """
        resource = resource_url_from_server_url(self.server_url)

        # If PRM provides a resource that's a valid parent, use it
        if self.protected_resource_metadata and self.protected_resource_metadata.resource:
            prm_resource = str(self.protected_resource_metadata.resource)
            if check_resource_allowed(requested_resource=resource, configured_resource=prm_resource):
                resource = prm_resource

        return resource


class OAuthClientProvider(httpx.Auth):
    """
    OAuth2 authentication for httpx.
    Handles OAuth flow with automatic client registration and token storage.
    """

    requires_response_body = True

    def __init__(
        self,
        server_url: str,
        client_metadata: OAuthClientMetadata,
        storage: TokenStorage,
        redirect_handler: Optional[Callable[[str], Awaitable[None]]] = None,
        callback_handler: Optional[Callable[[], Awaitable[tuple[str, str | None]]]] = None,
        timeout: float = 300.0,
    ):
        """Initialize OAuth2 authentication."""
        self.context = OAuthContext(
            server_url=server_url,
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
            timeout=timeout,
        )
        self._initialized = False

    async def _discover_protected_resource(self) -> httpx.Request:
        """Build discovery request for protected resource metadata."""
        auth_base_url = self.context.get_authorization_base_url(self.context.server_url)
        url = urljoin(auth_base_url, "/.well-known/oauth-protected-resource")
        return httpx.Request("GET", url, headers={MCP_PROTOCOL_VERSION: LATEST_PROTOCOL_VERSION})

    async def _handle_protected_resource_response(self, response: httpx.Response) -> None:
        """Handle discovery response."""
        if response.status_code == 200:
            try:
                content = await response.aread()
                metadata = ProtectedResourceMetadata.model_validate_json(content)
                self.context.protected_resource_metadata = metadata
                if metadata.authorization_servers:
                    self.context.auth_server_url = str(metadata.authorization_servers[0])
            except ValidationError:
                pass

    async def _discover_oauth_metadata(self) -> httpx.Request:
        """Build OAuth metadata discovery request."""
        if self.context.auth_server_url:
            base_url = self.context.get_authorization_base_url(self.context.auth_server_url)
        else:
            base_url = self.context.get_authorization_base_url(self.context.server_url)

        url = urljoin(base_url, "/.well-known/oauth-authorization-server")
        return httpx.Request("GET", url, headers={MCP_PROTOCOL_VERSION: LATEST_PROTOCOL_VERSION})

    async def _handle_oauth_metadata_response(self, response: httpx.Response) -> None:
        """Handle OAuth metadata response."""
        if response.status_code == 200:
            try:
                content = await response.aread()
                metadata = OAuthMetadata.model_validate_json(content)
                self.context.oauth_metadata = metadata
                # Apply default scope if none specified
                if self.context.client_metadata.scope is None and metadata.scopes_supported is not None:
                    self.context.client_metadata.scope = " ".join(metadata.scopes_supported)
            except ValidationError:
                pass

    async def _register_client(self) -> httpx.Request | None:
        """Build registration request or skip if already registered."""
        if self.context.client_info:
            return None

        if self.context.oauth_metadata and self.context.oauth_metadata.registration_endpoint:
            registration_url = str(self.context.oauth_metadata.registration_endpoint)
        else:
            auth_base_url = self.context.get_authorization_base_url(self.context.server_url)
            registration_url = urljoin(auth_base_url, "/register")

        registration_data = self.context.client_metadata.model_dump(by_alias=True, mode="json", exclude_none=True)

        return httpx.Request(
            "POST", registration_url, json=registration_data, headers={"Content-Type": "application/json"}
        )

    async def _handle_registration_response(self, response: httpx.Response) -> None:
        """Handle registration response."""
        if response.status_code not in (200, 201):
            raise OAuthRegistrationError(f"Registration failed: {response.status_code} {response.text}")

        try:
            content = await response.aread()
            client_info = OAuthClientInformationFull.model_validate_json(content)
            self.context.client_info = client_info
            await self.context.storage.set_client_info(client_info)
        except ValidationError as e:
            raise OAuthRegistrationError(f"Invalid registration response: {e}")

    async def _perform_authorization(self) -> httpx.Request:
        """Perform the authorization flow."""
        if not self.context.client_info:
            raise OAuthFlowError("No client info available for authorization")

        if "client_credentials" in self.context.client_info.grant_types:
            token_request = await self._exchange_token_client_credentials()
            return token_request
            pass
        else:
            auth_code, code_verifier = await self._perform_authorization_code_grant()
            token_request = await self._exchange_token_authorization_code(auth_code, code_verifier)
            return token_request

    async def _perform_authorization_code_grant(self) -> tuple[str, str]:
        """Perform the authorization redirect and get auth code."""
        if not self.context.redirect_handler:
            raise OAuthFlowError("No redirect handler provided for authorization code grant")
        if not self.context.callback_handler:
            raise OAuthFlowError("No callback handler provided for authorization code grant")

        if self.context.oauth_metadata and self.context.oauth_metadata.authorization_endpoint:
            auth_endpoint = str(self.context.oauth_metadata.authorization_endpoint)
        else:
            auth_base_url = self.context.get_authorization_base_url(self.context.server_url)
            auth_endpoint = urljoin(auth_base_url, "/authorize")

        if not self.context.client_info:
            raise OAuthFlowError("No client info available for authorization")

        # Generate PKCE parameters
        pkce_params = PKCEParameters.generate()
        state = secrets.token_urlsafe(32)

        auth_params = {
            "response_type": "code",
            "client_id": self.context.client_info.client_id,
            "redirect_uri": str(self.context.client_metadata.redirect_uris[0]),
            "state": state,
            "code_challenge": pkce_params.code_challenge,
            "code_challenge_method": "S256",
            "resource": self.context.get_resource_url(),  # RFC 8707
        }

        if self.context.client_metadata.scope:
            auth_params["scope"] = self.context.client_metadata.scope

        authorization_url = f"{auth_endpoint}?{urlencode(auth_params)}"
        await self.context.redirect_handler(authorization_url)

        # Wait for callback
        auth_code, returned_state = await self.context.callback_handler()

        if returned_state is None or not secrets.compare_digest(returned_state, state):
            raise OAuthFlowError(f"State parameter mismatch: {returned_state} != {state}")

        if not auth_code:
            raise OAuthFlowError("No authorization code received")

        # Return auth code and code verifier for token exchange
        return auth_code, pkce_params.code_verifier

    async def _exchange_token_authorization_code(self, auth_code: str, code_verifier: str) -> httpx.Request:
        """Build token exchange request for authorization_code flow."""
        if not self.context.client_info:
            raise OAuthFlowError("Missing client info")

        if self.context.oauth_metadata and self.context.oauth_metadata.token_endpoint:
            token_url = str(self.context.oauth_metadata.token_endpoint)
        else:
            auth_base_url = self.context.get_authorization_base_url(self.context.server_url)
            token_url = urljoin(auth_base_url, "/token")

        token_data = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": str(self.context.client_metadata.redirect_uris[0]),
            "client_id": self.context.client_info.client_id,
            "code_verifier": code_verifier,
            "resource": self.context.get_resource_url(),  # RFC 8707
        }

        if self.context.client_info.client_secret:
            token_data["client_secret"] = self.context.client_info.client_secret

        return httpx.Request(
            "POST", token_url, data=token_data, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

    async def _exchange_token_client_credentials(self) -> httpx.Request:
        """Build token exchange request for client_credentials flow."""
        if not self.context.client_info:
            raise OAuthFlowError("Missing client info")

        if self.context.oauth_metadata and self.context.oauth_metadata.token_endpoint:
            token_url = str(self.context.oauth_metadata.token_endpoint)
        else:
            auth_base_url = self.context.get_authorization_base_url(self.context.server_url)
            token_url = urljoin(auth_base_url, "/token")

        token_data = {
            "grant_type": "client_credentials",
            "resource": self.context.get_resource_url(),  # RFC 8707
        }

        if self.context.client_info.client_id:
            token_data["client_id"] = self.context.client_info.client_id
        if self.context.client_info.client_secret:
            token_data["client_secret"] = self.context.client_info.client_secret

        return httpx.Request(
            "POST", token_url, data=token_data, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

    async def _handle_token_response(self, response: httpx.Response) -> None:
        """Handle token exchange response."""
        if response.status_code != 200:
            raise OAuthTokenError(f"Token exchange failed: {response.status_code}")

        try:
            content = await response.aread()
            token_response = OAuthToken.model_validate_json(content)

            # Validate scopes
            if token_response.scope and self.context.client_metadata.scope:
                requested_scopes = set(self.context.client_metadata.scope.split())
                returned_scopes = set(token_response.scope.split())
                unauthorized_scopes = returned_scopes - requested_scopes
                if unauthorized_scopes:
                    raise OAuthTokenError(f"Server granted unauthorized scopes: {unauthorized_scopes}")

            self.context.current_tokens = token_response
            self.context.update_token_expiry(token_response)
            await self.context.storage.set_tokens(token_response)
        except ValidationError as e:
            raise OAuthTokenError(f"Invalid token response: {e}")

    async def _refresh_token(self) -> httpx.Request:
        """Build token refresh request."""
        if not self.context.current_tokens or not self.context.current_tokens.refresh_token:
            raise OAuthTokenError("No refresh token available")

        if not self.context.client_info:
            raise OAuthTokenError("No client info available")

        if self.context.oauth_metadata and self.context.oauth_metadata.token_endpoint:
            token_url = str(self.context.oauth_metadata.token_endpoint)
        else:
            auth_base_url = self.context.get_authorization_base_url(self.context.server_url)
            token_url = urljoin(auth_base_url, "/token")

        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": self.context.current_tokens.refresh_token,
            "client_id": self.context.client_info.client_id,
            "resource": self.context.get_resource_url(),  # RFC 8707
        }

        if self.context.client_info.client_secret:
            refresh_data["client_secret"] = self.context.client_info.client_secret

        return httpx.Request(
            "POST", token_url, data=refresh_data, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

    async def _handle_refresh_response(self, response: httpx.Response) -> bool:
        """Handle token refresh response. Returns True if successful."""
        if response.status_code != 200:
            logger.warning(f"Token refresh failed: {response.status_code}")
            self.context.clear_tokens()
            return False

        try:
            content = await response.aread()
            token_response = OAuthToken.model_validate_json(content)

            self.context.current_tokens = token_response
            self.context.update_token_expiry(token_response)
            await self.context.storage.set_tokens(token_response)

            return True
        except ValidationError as e:
            logger.error(f"Invalid refresh response: {e}")
            self.context.clear_tokens()
            return False

    async def _initialize(self) -> None:
        """Load stored tokens and client info."""
        self.context.current_tokens = await self.context.storage.get_tokens()
        self.context.client_info = await self.context.storage.get_client_info()
        self._initialized = True

    def _add_auth_header(self, request: httpx.Request) -> None:
        """Add authorization header to request if we have valid tokens."""
        if self.context.current_tokens and self.context.current_tokens.access_token:
            request.headers["Authorization"] = f"Bearer {self.context.current_tokens.access_token}"

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """HTTPX auth flow integration."""
        async with self.context.lock:
            if not self._initialized:
                await self._initialize()

            # Perform OAuth flow if not authenticated
            if not self.context.is_token_valid():
                try:
                    # OAuth flow must be inline due to generator constraints
                    # Step 1: Discover protected resource metadata (spec revision 2025-06-18)
                    discovery_request = await self._discover_protected_resource()
                    discovery_response = yield discovery_request
                    await self._handle_protected_resource_response(discovery_response)

                    # Step 2: Discover OAuth metadata
                    oauth_request = await self._discover_oauth_metadata()
                    oauth_response = yield oauth_request
                    await self._handle_oauth_metadata_response(oauth_response)

                    # Step 3: Register client if needed
                    registration_request = await self._register_client()
                    if registration_request:
                        registration_response = yield registration_request
                        await self._handle_registration_response(registration_response)

                    # Step 4: Perform authorization and complete token exchange
                    token_response = yield await self._perform_authorization()
                    await self._handle_token_response(token_response)
                except Exception as e:
                    logger.error(f"OAuth flow error: {e}")
                    raise

            # Add authorization header and make request
            self._add_auth_header(request)
            response = yield request

            # Handle 401 responses
            if response.status_code == 401 and self.context.can_refresh_token():
                # Try to refresh token
                refresh_request = await self._refresh_token()
                refresh_response = yield refresh_request

                if await self._handle_refresh_response(refresh_response):
                    # Retry original request with new token
                    self._add_auth_header(request)
                    yield request
                else:
                    # Refresh failed, need full re-authentication
                    self._initialized = False

                    # OAuth flow must be inline due to generator constraints
                    # Step 1: Discover protected resource metadata (spec revision 2025-06-18)
                    discovery_request = await self._discover_protected_resource()
                    discovery_response = yield discovery_request
                    await self._handle_protected_resource_response(discovery_response)

                    # Step 2: Discover OAuth metadata
                    oauth_request = await self._discover_oauth_metadata()
                    oauth_response = yield oauth_request
                    await self._handle_oauth_metadata_response(oauth_response)

                    # Step 3: Register client if needed
                    registration_request = await self._register_client()
                    if registration_request:
                        registration_response = yield registration_request
                        await self._handle_registration_response(registration_response)

                    # Step 4: Perform authorization and complete token exchange
                    token_response = yield await self._perform_authorization()
                    await self._handle_token_response(token_response)

                    # Retry with new tokens
                    self._add_auth_header(request)
                    yield request
