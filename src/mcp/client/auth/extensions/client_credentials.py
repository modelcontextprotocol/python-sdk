"""OAuth client credential extensions for MCP.

Provides OAuth providers for machine-to-machine authentication flows:
- ClientCredentialsOAuthProvider: For client_credentials with client_id + client_secret
- PrivateKeyJWTOAuthProvider: For client_credentials with private_key_jwt authentication
  (typically using a pre-built JWT from workload identity federation)
"""

import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal
from uuid import uuid4

import httpx2
import jwt
from pydantic import BaseModel, Field

from mcp.client.auth import OAuthClientProvider, OAuthFlowError, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata


class ClientCredentialsOAuthProvider(OAuthClientProvider):
    """OAuth provider for client_credentials grant with client_id + client_secret.

    This provider sets client_info directly, bypassing dynamic client registration.
    Use this when you already have client credentials (client_id and client_secret).

    Example:
        ```python
        provider = ClientCredentialsOAuthProvider(
            server_url="https://api.example.com",
            storage=my_token_storage,
            client_id="my-client-id",
            client_secret="my-client-secret",
        )
        ```
    """

    def __init__(
        self,
        server_url: str,
        storage: TokenStorage,
        client_id: str,
        client_secret: str,
        token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post"] = "client_secret_basic",
        scope: str | None = None,
    ) -> None:
        """Initialize client_credentials OAuth provider.

        Args:
            server_url: The MCP server URL.
            storage: Token storage implementation.
            client_id: The OAuth client ID.
            client_secret: The OAuth client secret.
            token_endpoint_auth_method: Authentication method for token endpoint.
                Either "client_secret_basic" (default) or "client_secret_post".
            scope: Optional space-separated list of scopes to request.
        """
        # Build minimal client_metadata for the base class
        client_metadata = OAuthClientMetadata(
            redirect_uris=None,
            grant_types=["client_credentials"],
            token_endpoint_auth_method=token_endpoint_auth_method,
            scope=scope,
        )
        super().__init__(server_url, client_metadata, storage, None, None)
        # Store client_info to be set during _initialize - no dynamic registration needed
        self._fixed_client_info = OAuthClientInformationFull(
            redirect_uris=None,
            client_id=client_id,
            client_secret=client_secret,
            grant_types=["client_credentials"],
            token_endpoint_auth_method=token_endpoint_auth_method,
            scope=scope,
        )

    async def _initialize(self) -> None:
        """Load stored tokens and set pre-configured client_info."""
        self.context.current_tokens = await self.context.storage.get_tokens()
        self.context.client_info = self._fixed_client_info
        self._initialized = True

    async def _perform_authorization(self) -> httpx2.Request:
        """Perform client_credentials authorization."""
        return await self._exchange_token_client_credentials()

    async def _exchange_token_client_credentials(self) -> httpx2.Request:
        """Build token exchange request for client_credentials grant."""
        token_data: dict[str, Any] = {
            "grant_type": "client_credentials",
        }

        headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}

        # Use standard auth methods (client_secret_basic, client_secret_post, none)
        token_data, headers = self.context.prepare_token_auth(token_data, headers)

        if self.context.should_include_resource_param(self.context.protocol_version):
            token_data["resource"] = self.context.get_resource_url()

        if self.context.client_metadata.scope:
            token_data["scope"] = self.context.client_metadata.scope

        token_url = self._get_token_endpoint()
        return httpx2.Request("POST", token_url, data=token_data, headers=headers)


def static_assertion_provider(token: str) -> Callable[[str], Awaitable[str]]:
    """Create an assertion provider that returns a static JWT token.

    Use this when you have a pre-built JWT (e.g., from workload identity federation)
    that doesn't need the audience parameter.

    Example:
        ```python
        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com",
            storage=my_token_storage,
            client_id="my-client-id",
            assertion_provider=static_assertion_provider(my_prebuilt_jwt),
        )
        ```

    Args:
        token: The pre-built JWT assertion string.

    Returns:
        An async callback suitable for use as an assertion_provider.
    """

    async def provider(audience: str) -> str:
        return token

    return provider


class SignedJWTParameters(BaseModel):
    """Parameters for creating SDK-signed JWT assertions.

    Use `create_assertion_provider()` to create an assertion provider callback
    for use with `PrivateKeyJWTOAuthProvider`.

    Example:
        ```python
        jwt_params = SignedJWTParameters(
            issuer="my-client-id",
            subject="my-client-id",
            signing_key=private_key_pem,
        )
        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com",
            storage=my_token_storage,
            client_id="my-client-id",
            assertion_provider=jwt_params.create_assertion_provider(),
        )
        ```
    """

    issuer: str = Field(description="Issuer for JWT assertions (typically client_id).")
    subject: str = Field(description="Subject identifier for JWT assertions (typically client_id).")
    signing_key: str = Field(description="Private key for JWT signing (PEM format).")
    signing_algorithm: str = Field(default="RS256", description="Algorithm for signing JWT assertions.")
    lifetime_seconds: int = Field(default=300, description="Lifetime of generated JWT in seconds.")
    additional_claims: dict[str, Any] | None = Field(default=None, description="Additional claims.")

    def create_assertion_provider(self) -> Callable[[str], Awaitable[str]]:
        """Create an assertion provider callback for use with PrivateKeyJWTOAuthProvider.

        Returns:
            An async callback that takes the audience (authorization server issuer URL)
            and returns a signed JWT assertion.
        """

        async def provider(audience: str) -> str:
            now = int(time.time())
            claims: dict[str, Any] = {
                "iss": self.issuer,
                "sub": self.subject,
                "aud": audience,
                "exp": now + self.lifetime_seconds,
                "iat": now,
                "jti": str(uuid4()),
            }
            if self.additional_claims:
                claims.update(self.additional_claims)

            return jwt.encode(claims, self.signing_key, algorithm=self.signing_algorithm)

        return provider


class PrivateKeyJWTOAuthProvider(OAuthClientProvider):
    """OAuth provider for client_credentials grant with private_key_jwt authentication.

    Uses RFC 7523 Section 2.2 for client authentication via JWT assertion.

    The JWT assertion's audience MUST be the authorization server's issuer identifier
    (per RFC 7523bis security updates). The `assertion_provider` callback receives
    this audience value and must return a JWT with that audience.

    **Option 1: Pre-built JWT via Workload Identity Federation**

    In production scenarios, the JWT assertion is typically obtained from a workload
    identity provider (e.g., GCP, AWS IAM, Azure AD):

        ```python
        async def get_workload_identity_token(audience: str) -> str:
            # Fetch JWT from your identity provider
            # The JWT's audience must match the provided audience parameter
            return await fetch_token_from_identity_provider(audience=audience)

        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com",
            storage=my_token_storage,
            client_id="my-client-id",
            assertion_provider=get_workload_identity_token,
        )
        ```

    **Option 2: Static pre-built JWT**

    If you have a static JWT that doesn't need the audience parameter:

        ```python
        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com",
            storage=my_token_storage,
            client_id="my-client-id",
            assertion_provider=static_assertion_provider(my_prebuilt_jwt),
        )
        ```

    **Option 3: SDK-signed JWT (for testing/simple setups)**

    For testing or simple deployments, use `SignedJWTParameters.create_assertion_provider()`:

        ```python
        jwt_params = SignedJWTParameters(
            issuer="my-client-id",
            subject="my-client-id",
            signing_key=private_key_pem,
        )
        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com",
            storage=my_token_storage,
            client_id="my-client-id",
            assertion_provider=jwt_params.create_assertion_provider(),
        )
        ```
    """

    def __init__(
        self,
        server_url: str,
        storage: TokenStorage,
        client_id: str,
        assertion_provider: Callable[[str], Awaitable[str]],
        scope: str | None = None,
    ) -> None:
        """Initialize private_key_jwt OAuth provider.

        Args:
            server_url: The MCP server URL.
            storage: Token storage implementation.
            client_id: The OAuth client ID.
            assertion_provider: Async callback that takes the audience (authorization
                server's issuer identifier) and returns a JWT assertion. Use
                `SignedJWTParameters.create_assertion_provider()` for SDK-signed JWTs,
                `static_assertion_provider()` for pre-built JWTs, or provide your own
                callback for workload identity federation.
            scope: Optional space-separated list of scopes to request.
        """
        # Build minimal client_metadata for the base class
        client_metadata = OAuthClientMetadata(
            redirect_uris=None,
            grant_types=["client_credentials"],
            token_endpoint_auth_method="private_key_jwt",
            scope=scope,
        )
        super().__init__(server_url, client_metadata, storage, None, None)
        self._assertion_provider = assertion_provider
        # Store client_info to be set during _initialize - no dynamic registration needed
        self._fixed_client_info = OAuthClientInformationFull(
            redirect_uris=None,
            client_id=client_id,
            grant_types=["client_credentials"],
            token_endpoint_auth_method="private_key_jwt",
            scope=scope,
        )

    async def _initialize(self) -> None:
        """Load stored tokens and set pre-configured client_info."""
        self.context.current_tokens = await self.context.storage.get_tokens()
        self.context.client_info = self._fixed_client_info
        self._initialized = True

    async def _perform_authorization(self) -> httpx2.Request:
        """Perform client_credentials authorization with private_key_jwt."""
        return await self._exchange_token_client_credentials()

    async def _add_client_authentication_jwt(self, *, token_data: dict[str, Any]) -> None:
        """Add JWT assertion for client authentication to token endpoint parameters."""
        if not self.context.oauth_metadata:
            raise OAuthFlowError("Missing OAuth metadata for private_key_jwt flow")  # pragma: no cover

        # Audience MUST be the issuer identifier of the authorization server
        # https://datatracker.ietf.org/doc/html/draft-ietf-oauth-rfc7523bis-01
        audience = str(self.context.oauth_metadata.issuer)
        assertion = await self._assertion_provider(audience)

        # RFC 7523 Section 2.2: client authentication via JWT
        token_data["client_assertion"] = assertion
        token_data["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"

    async def _exchange_token_client_credentials(self) -> httpx2.Request:
        """Build token exchange request for client_credentials grant with private_key_jwt."""
        token_data: dict[str, Any] = {
            "grant_type": "client_credentials",
        }

        headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}

        # Add JWT client authentication (RFC 7523 Section 2.2)
        await self._add_client_authentication_jwt(token_data=token_data)

        if self.context.should_include_resource_param(self.context.protocol_version):
            token_data["resource"] = self.context.get_resource_url()

        if self.context.client_metadata.scope:
            token_data["scope"] = self.context.client_metadata.scope

        token_url = self._get_token_endpoint()
        return httpx2.Request("POST", token_url, data=token_data, headers=headers)
