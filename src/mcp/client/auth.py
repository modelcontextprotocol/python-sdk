"""
OAuth2 Authentication implementation for HTTPX.

Implements authorization code flow with PKCE and automatic token refresh.
"""

import base64
import hashlib
import logging
import re
import secrets
import string
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol
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
    redirect_handler: Callable[[str], Awaitable[None]]
    callback_handler: Callable[[], Awaitable[tuple[str, str | None]]]
    timeout: float = 300.0

    # Discovered metadata
    protected_resource_metadata: ProtectedResourceMetadata | None = None
    oauth_metadata: OAuthMetadata | None = None
    auth_server_url: str | None = None
    protocol_version: str | None = None

    # Client registration
    client_info: OAuthClientInformationFull | None = None

    # Token management
    current_tokens: OAuthToken | None = None
    token_expiry_time: float | None = None

    # State
    lock: anyio.Lock = field(default_factory=anyio.Lock)

    # Discovery state for fallback support
    discovery_base_url: str | None = None
    discovery_pathname: str | None = None

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
        """Check if the current token is valid."""
        return bool(
            self.current_tokens
            and self.current_tokens.access_token
            and (not self.token_expiry_time or time.time() <= self.token_expiry_time)
        )

    def can_refresh_token(self) -> bool:
        """Check if the token can be refreshed."""
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

    def should_include_resource_param(self, protocol_version: str | None = None) -> bool:
        """Determine if the resource parameter should be included in OAuth requests.

        Returns True if:
        - Protected resource metadata is available, OR
        - MCP-Protocol-Version header is 2025-06-18 or later
        """
        # If we have protected resource metadata, include the resource param
        if self.protected_resource_metadata is not None:
            return True

        # If no protocol version provided, don't include resource param
        if not protocol_version:
            return False

        # Check if protocol version is 2025-06-18 or later
        # Version format is YYYY-MM-DD, so string comparison works
        return protocol_version >= "2025-06-18"


class BaseOAuthProvider(httpx.Auth):
    """Common OAuth utilities for discovery, registration, and client auth."""

    requires_response_body = True

    def __init__(
        self,
        server_url: str,
        client_metadata: OAuthClientMetadata,
        storage: TokenStorage,
        timeout: float = 300.0,
    ) -> None:
        self.server_url = server_url
        self.client_metadata = client_metadata
        self.storage = storage
        self.timeout = timeout
        self._metadata: OAuthMetadata | None = None
        self._client_info: OAuthClientInformationFull | None = None

    def _get_authorization_base_url(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _get_discovery_urls(self, server_url: str | None = None) -> list[str]:
        url = server_url or self.server_url
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        urls: list[str] = []

        if parsed.path and parsed.path != "/":
            oauth_path = f"/.well-known/oauth-authorization-server{parsed.path.rstrip('/')}"
            urls.append(urljoin(base_url, oauth_path))
        urls.append(urljoin(base_url, "/.well-known/oauth-authorization-server"))
        if parsed.path and parsed.path != "/":
            oidc_path = f"/.well-known/openid-configuration{parsed.path.rstrip('/')}"
            urls.append(urljoin(base_url, oidc_path))
        urls.append(f"{url.rstrip('/')}/.well-known/openid-configuration")
        return urls

    def _create_oauth_metadata_request(self, url: str) -> httpx.Request:
        return httpx.Request("GET", url, headers={MCP_PROTOCOL_VERSION: LATEST_PROTOCOL_VERSION})

    async def _handle_oauth_metadata_response(self, response: httpx.Response) -> None:
        content = await response.aread()
        metadata = OAuthMetadata.model_validate_json(content)
        self._metadata = metadata
        if self.client_metadata.scope is None and metadata.scopes_supported is not None:
            self.client_metadata.scope = " ".join(metadata.scopes_supported)

    def _create_registration_request(self, metadata: OAuthMetadata | None = None) -> httpx.Request | None:
        if self._client_info:
            return None
        if metadata and metadata.registration_endpoint:
            registration_url = str(metadata.registration_endpoint)
        else:
            auth_base_url = self._get_authorization_base_url(self.server_url)
            registration_url = urljoin(auth_base_url, "/register")
        registration_data = self.client_metadata.model_dump(by_alias=True, mode="json", exclude_none=True)
        return httpx.Request(
            "POST",
            registration_url,
            json=registration_data,
            headers={"Content-Type": "application/json"},
        )

    async def _handle_registration_response(self, response: httpx.Response) -> None:
        if response.status_code not in (200, 201):
            await response.aread()
            raise OAuthRegistrationError(f"Registration failed: {response.status_code} {response.text}")
        content = await response.aread()
        client_info = OAuthClientInformationFull.model_validate_json(content)
        self._client_info = client_info
        await self.storage.set_client_info(client_info)

    def _apply_client_auth(
        self,
        token_data: dict[str, str],
        headers: dict[str, str],
        client_info: OAuthClientInformationFull,
    ) -> None:
        auth_method = "client_secret_post"
        if self._metadata and self._metadata.token_endpoint_auth_methods_supported:
            supported = self._metadata.token_endpoint_auth_methods_supported
            if "client_secret_basic" in supported:
                auth_method = "client_secret_basic"
            elif "client_secret_post" in supported:
                auth_method = "client_secret_post"
        if auth_method == "client_secret_basic":
            if client_info.client_secret is None:
                raise OAuthFlowError("Client secret required for client_secret_basic")
            credential = f"{client_info.client_id}:{client_info.client_secret}"
            headers["Authorization"] = f"Basic {base64.b64encode(credential.encode()).decode()}"
        else:
            token_data["client_id"] = client_info.client_id
            if client_info.client_secret:
                token_data["client_secret"] = client_info.client_secret


class OAuthClientProvider(BaseOAuthProvider):
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
        redirect_handler: Callable[[str], Awaitable[None]],
        callback_handler: Callable[[], Awaitable[tuple[str, str | None]]],
        timeout: float = 300.0,
    ):
        """Initialize OAuth2 authentication."""
        super().__init__(server_url, client_metadata, storage, timeout)
        self.context = OAuthContext(
            server_url=server_url,
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
            timeout=timeout,
        )
        self._initialized = False

    def _extract_field_from_www_auth(self, init_response: httpx.Response, field_name: str) -> str | None:
        """
        Extract field from WWW-Authenticate header.

        Returns:
            Field value if found in WWW-Authenticate header, None otherwise
        """
        www_auth_header = init_response.headers.get("WWW-Authenticate")
        if not www_auth_header:
            return None

        # Pattern matches: field_name="value" or field_name=value (unquoted)
        pattern = rf'{field_name}=(?:"([^"]+)"|([^\s,]+))'
        match = re.search(pattern, www_auth_header)

        if match:
            # Return quoted value if present, otherwise unquoted value
            return match.group(1) or match.group(2)

        return None

    def _extract_resource_metadata_from_www_auth(self, init_response: httpx.Response) -> str | None:
        """
        Extract protected resource metadata URL from WWW-Authenticate header as per RFC9728.

        Returns:
            Resource metadata URL if found in WWW-Authenticate header, None otherwise
        """
        if not init_response or init_response.status_code != 401:
            return None

        return self._extract_field_from_www_auth(init_response, "resource_metadata")

    def _extract_scope_from_www_auth(self, init_response: httpx.Response) -> str | None:
        """
        Extract scope parameter from WWW-Authenticate header as per RFC6750.

        Returns:
            Scope string if found in WWW-Authenticate header, None otherwise
        """
        return self._extract_field_from_www_auth(init_response, "scope")

    async def _discover_protected_resource(self, init_response: httpx.Response) -> httpx.Request:
        # RFC9728: Try to extract resource_metadata URL from WWW-Authenticate header of the initial response
        url = self._extract_resource_metadata_from_www_auth(init_response)

        if not url:
            # Fallback to well-known discovery
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
        else:
            raise OAuthFlowError(f"Protected Resource Metadata request failed: {response.status_code}")

    def _select_scopes(self, init_response: httpx.Response) -> None:
        """Select scopes as outlined in the 'Scope Selection Strategy in the MCP spec."""
        # Per MCP spec, scope selection priority order:
        # 1. Use scope from WWW-Authenticate header (if provided)
        # 2. Use all scopes from PRM scopes_supported (if available)
        # 3. Omit scope parameter if neither is available
        #
        www_authenticate_scope = self._extract_scope_from_www_auth(init_response)
        if www_authenticate_scope is not None:
            # Priority 1: WWW-Authenticate header scope
            self.context.client_metadata.scope = www_authenticate_scope
        elif (
            self.context.protected_resource_metadata is not None
            and self.context.protected_resource_metadata.scopes_supported is not None
        ):
            # Priority 2: PRM scopes_supported
            self.context.client_metadata.scope = " ".join(self.context.protected_resource_metadata.scopes_supported)
        else:
            # Priority 3: Omit scope parameter
            self.context.client_metadata.scope = None

    # Discovery and registration helpers provided by BaseOAuthProvider

    async def _perform_authorization(self) -> tuple[str, str]:
        """Perform the authorization redirect and get auth code."""
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
        }

        # Only include resource param if conditions are met
        if self.context.should_include_resource_param(self.context.protocol_version):
            auth_params["resource"] = self.context.get_resource_url()  # RFC 8707

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

    async def _exchange_token(self, auth_code: str, code_verifier: str) -> httpx.Request:
        """Build token exchange request."""
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
            "code_verifier": code_verifier,
        }

        # Only include resource param if conditions are met
        if self.context.should_include_resource_param(self.context.protocol_version):
            token_data["resource"] = self.context.get_resource_url()  # RFC 8707

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        self._apply_client_auth(token_data, headers, self.context.client_info)

        return httpx.Request("POST", token_url, data=token_data, headers=headers)

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
        }

        # Only include resource param if conditions are met
        if self.context.should_include_resource_param(self.context.protocol_version):
            refresh_data["resource"] = self.context.get_resource_url()  # RFC 8707

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        self._apply_client_auth(refresh_data, headers, self.context.client_info)

        return httpx.Request("POST", token_url, data=refresh_data, headers=headers)

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
        except ValidationError:
            logger.exception("Invalid refresh response")
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

            # Capture protocol version from request headers
            self.context.protocol_version = request.headers.get(MCP_PROTOCOL_VERSION)

            if not self.context.is_token_valid() and self.context.can_refresh_token():
                # Try to refresh token
                refresh_request = await self._refresh_token()
                refresh_response = yield refresh_request

                if not await self._handle_refresh_response(refresh_response):
                    # Refresh failed, need full re-authentication
                    self._initialized = False

            if self.context.is_token_valid():
                self._add_auth_header(request)

            response = yield request

            if response.status_code == 401:
                # Perform full OAuth flow
                try:
                    # OAuth flow must be inline due to generator constraints
                    # Step 1: Discover protected resource metadata (RFC9728 with WWW-Authenticate support)
                    discovery_request = await self._discover_protected_resource(response)
                    discovery_response = yield discovery_request
                    await self._handle_protected_resource_response(discovery_response)

                    # Step 2: Apply scope selection strategy
                    self._select_scopes(response)

                    # Step 3: Discover OAuth metadata (with fallback for legacy servers)
                    discovery_urls = self._get_discovery_urls(
                        self.context.auth_server_url or self.context.server_url
                    )
                    for url in discovery_urls:
                        oauth_metadata_request = self._create_oauth_metadata_request(url)
                        oauth_metadata_response = yield oauth_metadata_request

                        if oauth_metadata_response.status_code == 200:
                            try:
                                await self._handle_oauth_metadata_response(oauth_metadata_response)
                                self.context.oauth_metadata = self._metadata
                                break
                            except ValidationError:
                                continue
                        elif oauth_metadata_response.status_code < 400 or oauth_metadata_response.status_code >= 500:
                            break  # Non-4XX error, stop trying

                    # Step 4: Register client if needed
                    registration_request = self._create_registration_request(self._metadata)
                    if registration_request:
                        registration_response = yield registration_request
                        await self._handle_registration_response(registration_response)
                        self.context.client_info = self._client_info

                    # Step 5: Perform authorization
                    auth_code, code_verifier = await self._perform_authorization()

                    # Step 6: Exchange authorization code for tokens
                    token_request = await self._exchange_token(auth_code, code_verifier)
                    token_response = yield token_request
                    await self._handle_token_response(token_response)
                except Exception:
                    logger.exception("OAuth flow error")
                    raise

                # Retry with new tokens
                self._add_auth_header(request)
                yield request

            elif response.status_code == 403:
                # Step 1: Extract error field from WWW-Authenticate header
                error = self._extract_field_from_www_auth(response, "error")

                # Step 2: Check if we need to step-up authorization
                if error == "insufficient_scope":
                    try:
                        # Step 2a: Update the required scopes
                        self._select_scopes(response)

                        # Step 2b: Perform (re-)authorization
                        auth_code, code_verifier = await self._perform_authorization()

                        # Step 2c: Exchange authorization code for tokens
                        token_request = await self._exchange_token(auth_code, code_verifier)
                        token_response = yield token_request
                        await self._handle_token_response(token_response)
                    except Exception:
                        logger.exception("OAuth flow error")
                        raise

                    # Retry with new tokens
                    self._add_auth_header(request)
                    yield request


class ClientCredentialsProvider(BaseOAuthProvider):
    """HTTPX auth using the OAuth2 client credentials grant."""

    def __init__(
        self,
        server_url: str,
        client_metadata: OAuthClientMetadata,
        storage: TokenStorage,
        resource: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(server_url, client_metadata, storage, timeout)
        self.resource = resource or resource_url_from_server_url(server_url)
        self._current_tokens: OAuthToken | None = None
        self._token_expiry_time: float | None = None
        self._token_lock = anyio.Lock()

    def _has_valid_token(self) -> bool:
        if not self._current_tokens or not self._current_tokens.access_token:
            return False
        if self._token_expiry_time and time.time() > self._token_expiry_time:
            return False
        return True

    async def _validate_token_scopes(self, token_response: OAuthToken) -> None:
        if not token_response.scope:
            return
        requested_scopes: set[str] = set()
        if self.client_metadata.scope:
            requested_scopes = set(self.client_metadata.scope.split())
            returned_scopes = set(token_response.scope.split())
            unauthorized_scopes = returned_scopes - requested_scopes
            if unauthorized_scopes:
                raise Exception(f"Server granted unauthorized scopes: {unauthorized_scopes}.")
        else:
            granted = set(token_response.scope.split())
            logger.debug(
                "No explicit scopes requested, accepting server-granted scopes: %s",
                granted,
            )

    async def initialize(self) -> None:
        self._current_tokens = await self.storage.get_tokens()
        self._client_info = await self.storage.get_client_info()

    async def _get_or_register_client(self) -> OAuthClientInformationFull:
        if not self._client_info:
            request = self._create_registration_request(self._metadata)
            if request:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response: httpx.Response = await client.send(request)
                await self._handle_registration_response(response)
        assert self._client_info
        return self._client_info

    async def _request_token(self) -> None:
        if not self._metadata:
            discovery_urls = self._get_discovery_urls(self.server_url)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for url in discovery_urls:
                    req = self._create_oauth_metadata_request(url)
                    resp: httpx.Response = await client.send(req)
                    if resp.status_code == 200:
                        try:
                            await self._handle_oauth_metadata_response(resp)
                            break
                        except ValidationError:
                            continue
                    elif resp.status_code < 400 or resp.status_code >= 500:
                        break

        client_info = await self._get_or_register_client()

        if self._metadata and self._metadata.token_endpoint:
            token_url = str(self._metadata.token_endpoint)
        else:
            auth_base_url = self._get_authorization_base_url(self.server_url)
            token_url = urljoin(auth_base_url, "/token")

        token_data: dict[str, str] = {
            "grant_type": "client_credentials",
            "resource": self.resource,
        }
        if self.client_metadata.scope:
            token_data["scope"] = self.client_metadata.scope
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        self._apply_client_auth(token_data, headers, client_info)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response: httpx.Response = await client.post(
                token_url,
                data=token_data,
                headers=headers,
            )

        if response.status_code != 200:
            raise Exception(f"Token request failed: {response.status_code} {response.text}")

        token_response = OAuthToken.model_validate(response.json())
        await self._validate_token_scopes(token_response)

        if token_response.expires_in:
            self._token_expiry_time = time.time() + token_response.expires_in
        else:
            self._token_expiry_time = None

        await self.storage.set_tokens(token_response)
        self._current_tokens = token_response

    async def ensure_token(self) -> None:
        async with self._token_lock:
            if self._has_valid_token():
                return
            await self._request_token()

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        if not self._has_valid_token():
            await self.initialize()
            await self.ensure_token()
        if self._current_tokens and self._current_tokens.access_token:
            request.headers["Authorization"] = f"Bearer {self._current_tokens.access_token}"
        response = yield request
        if response.status_code == 401:
            self._current_tokens = None


class TokenExchangeProvider(BaseOAuthProvider):
    """OAuth2 token exchange based on RFC 8693."""

    def __init__(
        self,
        server_url: str,
        client_metadata: OAuthClientMetadata,
        storage: TokenStorage,
        subject_token_supplier: Callable[[], Awaitable[str]],
        subject_token_type: str = "access_token",
        actor_token_supplier: Callable[[], Awaitable[str]] | None = None,
        actor_token_type: str | None = None,
        audience: str | None = None,
        resource: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(server_url, client_metadata, storage, timeout)
        self.subject_token_supplier = subject_token_supplier
        self.subject_token_type = subject_token_type
        self.actor_token_supplier = actor_token_supplier
        self.actor_token_type = actor_token_type
        self.audience = audience
        self.resource = resource or resource_url_from_server_url(server_url)
        self._current_tokens: OAuthToken | None = None
        self._token_expiry_time: float | None = None
        self._token_lock = anyio.Lock()

    def _has_valid_token(self) -> bool:
        if not self._current_tokens or not self._current_tokens.access_token:
            return False
        if self._token_expiry_time and time.time() > self._token_expiry_time:
            return False
        return True

    async def _validate_token_scopes(self, token_response: OAuthToken) -> None:
        if not token_response.scope:
            return
        requested_scopes: set[str] = set()
        if self.client_metadata.scope:
            requested_scopes = set(self.client_metadata.scope.split())
            returned_scopes = set(token_response.scope.split())
            unauthorized_scopes = returned_scopes - requested_scopes
            if unauthorized_scopes:
                raise Exception(f"Server granted unauthorized scopes: {unauthorized_scopes}.")
        else:
            granted = set(token_response.scope.split())
            logger.debug(
                "No explicit scopes requested, accepting server-granted scopes: %s",
                granted,
            )

    async def initialize(self) -> None:
        self._current_tokens = await self.storage.get_tokens()
        self._client_info = await self.storage.get_client_info()

    async def _get_or_register_client(self) -> OAuthClientInformationFull:
        if not self._client_info:
            request = self._create_registration_request(self._metadata)
            if request:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response: httpx.Response = await client.send(request)
                await self._handle_registration_response(response)
        assert self._client_info
        return self._client_info

    async def _request_token(self) -> None:
        if not self._metadata:
            discovery_urls = self._get_discovery_urls(self.server_url)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for url in discovery_urls:
                    req = self._create_oauth_metadata_request(url)
                    resp: httpx.Response = await client.send(req)
                    if resp.status_code == 200:
                        try:
                            await self._handle_oauth_metadata_response(resp)
                            break
                        except ValidationError:
                            continue
                    elif resp.status_code < 400 or resp.status_code >= 500:
                        break

        client_info = await self._get_or_register_client()

        if self._metadata and self._metadata.token_endpoint:
            token_url = str(self._metadata.token_endpoint)
        else:
            auth_base_url = self._get_authorization_base_url(self.server_url)
            token_url = urljoin(auth_base_url, "/token")

        subject_token = await self.subject_token_supplier()
        actor_token = await self.actor_token_supplier() if self.actor_token_supplier else None

        token_data: dict[str, str] = {
            "grant_type": "token_exchange",
            "subject_token": subject_token,
            "subject_token_type": self.subject_token_type,
        }
        if actor_token:
            token_data["actor_token"] = actor_token
        if self.actor_token_type:
            token_data["actor_token_type"] = self.actor_token_type
        if self.audience:
            token_data["audience"] = self.audience
        if self.resource:
            token_data["resource"] = self.resource
        if self.client_metadata.scope:
            token_data["scope"] = self.client_metadata.scope

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        self._apply_client_auth(token_data, headers, client_info)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response: httpx.Response = await client.post(
                token_url,
                data=token_data,
                headers=headers,
            )

        if response.status_code != 200:
            raise Exception(f"Token request failed: {response.status_code} {response.text}")

        token_response = OAuthToken.model_validate(response.json())
        await self._validate_token_scopes(token_response)

        if token_response.expires_in:
            self._token_expiry_time = time.time() + token_response.expires_in
        else:
            self._token_expiry_time = None

        await self.storage.set_tokens(token_response)
        self._current_tokens = token_response

    async def ensure_token(self) -> None:
        async with self._token_lock:
            if self._has_valid_token():
                return
            await self._request_token()

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        if not self._has_valid_token():
            await self.initialize()
            await self.ensure_token()
        if self._current_tokens and self._current_tokens.access_token:
            request.headers["Authorization"] = f"Bearer {self._current_tokens.access_token}"
        response = yield request
        if response.status_code == 401:
            self._current_tokens = None
