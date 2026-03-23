"""Enterprise Managed Authorization extension for MCP (SEP-990).

Implements RFC 8693 Token Exchange and RFC 7523 JWT Bearer Grant for
enterprise SSO integration.
"""

import logging
import time
from json import JSONDecodeError
from typing import cast

import httpx
import jwt
from pydantic import BaseModel, Field
from typing_extensions import NotRequired, Required, TypedDict

from mcp.client.auth import OAuthClientProvider, OAuthFlowError, OAuthTokenError, TokenStorage
from mcp.shared.auth import OAuthClientMetadata

logger = logging.getLogger(__name__)


class TokenExchangeRequestData(TypedDict):
    """Type definition for RFC 8693 Token Exchange request data.

    Required fields are those mandated by RFC 8693.
    Optional fields (NotRequired) may be included based on IdP requirements.
    """

    grant_type: Required[str]
    requested_token_type: Required[str]
    audience: Required[str]
    resource: Required[str]
    subject_token: Required[str]
    subject_token_type: Required[str]
    scope: NotRequired[str]
    client_id: NotRequired[str]
    client_secret: NotRequired[str]


class JWTBearerGrantRequestData(TypedDict):
    """Type definition for RFC 7523 JWT Bearer Grant request data.

    Required fields are those mandated by RFC 7523.
    Optional fields (NotRequired) are for client authentication.
    """

    grant_type: Required[str]
    assertion: Required[str]
    client_id: NotRequired[str]
    client_secret: NotRequired[str]


class TokenExchangeParameters(BaseModel):
    """Parameters for RFC 8693 Token Exchange request."""

    requested_token_type: str = Field(
        default="urn:ietf:params:oauth:token-type:id-jag",
        description="Type of token being requested (ID-JAG)",
    )

    audience: str = Field(
        ...,
        description="Issuer URL of the MCP Server's authorization server",
    )

    resource: str = Field(
        ...,
        description="RFC 9728 Resource Identifier of the MCP Server",
    )

    scope: str | None = Field(
        default=None,
        description="Space-separated list of scopes being requested",
    )

    subject_token: str = Field(
        ...,
        description="ID Token or SAML assertion for the end user",
    )

    subject_token_type: str = Field(
        ...,
        description="Type of subject token (id_token or saml2)",
    )

    @classmethod
    def from_id_token(
        cls,
        id_token: str,
        mcp_server_auth_issuer: str,
        mcp_server_resource_id: str,
        scope: str | None = None,
    ) -> "TokenExchangeParameters":
        """Create parameters for OIDC ID Token exchange."""
        return cls(
            subject_token=id_token,
            subject_token_type="urn:ietf:params:oauth:token-type:id_token",
            audience=mcp_server_auth_issuer,
            resource=mcp_server_resource_id,
            scope=scope,
        )

    @classmethod
    def from_saml_assertion(
        cls,
        saml_assertion: str,
        mcp_server_auth_issuer: str,
        mcp_server_resource_id: str,
        scope: str | None = None,
    ) -> "TokenExchangeParameters":
        """Create parameters for SAML assertion exchange."""
        return cls(
            subject_token=saml_assertion,
            subject_token_type="urn:ietf:params:oauth:token-type:saml2",
            audience=mcp_server_auth_issuer,
            resource=mcp_server_resource_id,
            scope=scope,
        )


class IDJAGTokenExchangeResponse(BaseModel):
    """Response from RFC 8693 Token Exchange for ID-JAG."""

    issued_token_type: str = Field(
        ...,
        description="Type of token issued (should be id-jag)",
    )

    access_token: str = Field(
        ...,
        description="The ID-JAG token (named access_token per RFC 8693)",
    )

    token_type: str = Field(
        ...,
        description="Token type (should be N_A for ID-JAG)",
    )

    scope: str | None = Field(
        default=None,
        description="Granted scopes",
    )

    expires_in: int | None = Field(
        default=None,
        description="Lifetime in seconds",
    )

    @property
    def id_jag(self) -> str:
        """Get the ID-JAG token."""
        return self.access_token


class IDJAGClaims(BaseModel):
    """Claims structure for Identity Assertion JWT Authorization Grant."""

    model_config = {"extra": "allow"}

    # JWT header
    typ: str = Field(
        ...,
        description="JWT type - must be 'oauth-id-jag+jwt'",
    )

    # Required claims
    jti: str = Field(..., description="Unique JWT ID")
    iss: str = Field(..., description="IdP issuer URL")
    sub: str = Field(..., description="Subject (user) identifier")
    aud: str = Field(..., description="MCP Server's auth server issuer")
    resource: str = Field(..., description="MCP Server resource identifier")
    client_id: str = Field(..., description="MCP Client identifier")
    exp: int = Field(..., description="Expiration timestamp")
    iat: int = Field(..., description="Issued-at timestamp")

    # Optional claims
    scope: str | None = Field(None, description="Space-separated scopes")
    email: str | None = Field(None, description="User email")


class EnterpriseAuthOAuthClientProvider(OAuthClientProvider):
    """OAuth client provider for Enterprise Managed Authorization (SEP-990).

    Implements:
    - RFC 8693: Token Exchange (ID Token → ID-JAG)
    - RFC 7523: JWT Bearer Grant (ID-JAG → Access Token)

    Concurrency & Thread Safety:
    - SAFE: Concurrent requests within a single asyncio event loop. Token operations
      are protected by the parent class's `OAuthContext.lock`.
    - UNSAFE: Sharing a provider instance across multiple OS threads. Each thread
      must instantiate its own provider and event loop.
    - Note: Ensure any shared `TokenStorage` implementation is async-safe.
    """

    # Default ID-JAG expiry when IdP doesn't provide expires_in
    # 15 minutes is a conservative default for enterprise environments
    DEFAULT_ID_JAG_EXPIRY_SECONDS = 900

    def __init__(
        self,
        server_url: str,
        client_metadata: OAuthClientMetadata,
        storage: TokenStorage,
        idp_token_endpoint: str,
        token_exchange_params: TokenExchangeParameters,
        timeout: float = 300.0,
        idp_client_id: str | None = None,
        idp_client_secret: str | None = None,
        default_id_jag_expiry: int = DEFAULT_ID_JAG_EXPIRY_SECONDS,
    ) -> None:
        """Initialize Enterprise Auth OAuth Client.

        Args:
            server_url: MCP server URL
            client_metadata: OAuth client metadata
            storage: Token storage implementation
            idp_token_endpoint: Enterprise IdP token endpoint URL
            token_exchange_params: Token exchange parameters
            timeout: Request timeout in seconds
            idp_client_id: Optional client ID registered with the IdP for token exchange
            idp_client_secret: Optional client secret registered with the IdP for token exchange
            default_id_jag_expiry: Fallback ID-JAG expiry in seconds if the IdP
                omits `expires_in` (default: 900s/15m). Adjust to balance token
                freshness against IdP request load.
        """
        super().__init__(
            server_url=server_url,
            client_metadata=client_metadata,
            storage=storage,
            timeout=timeout,
        )
        self.idp_token_endpoint = idp_token_endpoint
        self.token_exchange_params = token_exchange_params
        self.idp_client_id = idp_client_id
        self.idp_client_secret = idp_client_secret
        self.default_id_jag_expiry = default_id_jag_expiry
        self._id_jag: str | None = None
        self._id_jag_expiry: float | None = None

        # Validate client authentication configuration
        if idp_client_secret is not None and idp_client_id is None:
            logger.warning(
                "idp_client_secret provided without idp_client_id. "
                "The secret will be sent to the IdP but may be ignored. "
                "Consider providing both idp_client_id and idp_client_secret together."
            )

    async def exchange_token_for_id_jag(
        self,
        client: httpx.AsyncClient,
    ) -> str:
        """Exchange ID Token for ID-JAG using RFC 8693 Token Exchange.

        Note: Overrides the configured `audience` with the discovered OAuth
            issuer URL (if available) to satisfy MCP server `aud` claim requirements.

        Args:
            client: HTTP client for making requests

        Returns:
            The ID-JAG token string

        Raises:
            OAuthTokenError: If token exchange fails
        """
        logger.debug("Starting token exchange for ID-JAG")

        audience = self.token_exchange_params.audience
        if self.context.oauth_metadata and self.context.oauth_metadata.issuer:
            discovered_issuer = str(self.context.oauth_metadata.issuer)
            if audience != discovered_issuer:
                logger.warning(
                    f"Overriding audience '{audience}' with discovered issuer '{discovered_issuer}'. "
                    f"To prevent this, set token_exchange_params.audience to the issuer URL."
                )
            audience = discovered_issuer

        # Build token exchange request
        token_data: TokenExchangeRequestData = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "requested_token_type": self.token_exchange_params.requested_token_type,
            "audience": audience,
            "resource": self.token_exchange_params.resource,
            "subject_token": self.token_exchange_params.subject_token,
            "subject_token_type": self.token_exchange_params.subject_token_type,
        }

        if self.token_exchange_params.scope and self.token_exchange_params.scope.strip():
            token_data["scope"] = self.token_exchange_params.scope

        # Add IdP client authentication if provided
        if self.idp_client_id is not None:
            token_data["client_id"] = self.idp_client_id
        if self.idp_client_secret is not None:
            token_data["client_secret"] = self.idp_client_secret

        try:
            response = await client.post(
                self.idp_token_endpoint,
                data=token_data,
                timeout=self.context.timeout,
            )

            if response.status_code != 200:
                error_data: dict[str, str] = {}
                try:
                    if response.headers.get("content-type", "").startswith("application/json"):
                        error_data = response.json()
                except JSONDecodeError:
                    # Response is not valid JSON, use default error handling
                    pass

                error: str = error_data.get("error", "unknown_error")
                error_description: str = error_data.get(
                    "error_description", f"Token exchange failed (HTTP {response.status_code})"
                )
                raise OAuthTokenError(f"Token exchange failed: {error} - {error_description}")

            # Parse response
            token_response = IDJAGTokenExchangeResponse.model_validate_json(response.content)

            # Validate response
            if token_response.issued_token_type != "urn:ietf:params:oauth:token-type:id-jag":
                raise OAuthTokenError(f"Unexpected token type: {token_response.issued_token_type}")

            if token_response.token_type != "N_A":
                logger.warning(f"Expected token_type 'N_A', got '{token_response.token_type}'")

            logger.debug("Successfully obtained ID-JAG")
            self._id_jag = token_response.id_jag

            # Track ID-JAG expiry to avoid using stale cached tokens
            if token_response.expires_in:
                self._id_jag_expiry = time.time() + token_response.expires_in
            else:
                # If no expires_in, use configured default expiry
                self._id_jag_expiry = time.time() + self.default_id_jag_expiry
                logger.debug(
                    f"IdP did not provide expires_in, using default expiry of "
                    f"{self.default_id_jag_expiry} seconds for ID-JAG"
                )

            return token_response.id_jag

        except httpx.HTTPError as e:
            raise OAuthTokenError(f"HTTP error during token exchange: {e}") from e

    async def exchange_id_jag_for_access_token(
        self,
        id_jag: str,
    ) -> httpx.Request:
        """Build JWT bearer grant request to exchange ID-JAG for access token (RFC 7523).

        Builds the request without executing it. HTTP execution and error parsing
        are deferred to the parent class's `async_auth_flow` for consistency.

        Args:
            id_jag: The ID-JAG token

        Returns:
            httpx.Request for the JWT bearer grant

        Raises:
            OAuthFlowError: If OAuth metadata not discovered
        """
        logger.info("Building JWT bearer grant request for ID-JAG")

        # Discover token endpoint from MCP server if not already done
        if not self.context.oauth_metadata or not self.context.oauth_metadata.token_endpoint:
            raise OAuthFlowError("MCP server token endpoint not discovered")

        token_endpoint = str(self.context.oauth_metadata.token_endpoint)

        # Build JWT bearer grant request
        token_data: JWTBearerGrantRequestData = {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": id_jag,
        }

        # Add client authentication
        if self.context.client_info:
            # Default to client_secret_basic if not specified (per OAuth 2.0 spec)
            if self.context.client_info.token_endpoint_auth_method is None:
                self.context.client_info.token_endpoint_auth_method = "client_secret_basic"

            if self.context.client_info.client_id is not None:
                token_data["client_id"] = self.context.client_info.client_id
            if self.context.client_info.client_secret is not None:
                token_data["client_secret"] = self.context.client_info.client_secret

        # Apply client authentication method (handles client_secret_basic vs client_secret_post)
        headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}
        # Cast to dict[str, str] for prepare_token_auth compatibility
        # Double-cast to bypass TypedDict strictness for prepare_token_auth
        data_dict = cast(dict[str, str], cast(object, token_data))
        data_dict, headers = self.context.prepare_token_auth(data_dict, headers)

        return httpx.Request("POST", token_endpoint, data=data_dict, headers=headers)

    async def _perform_authorization(self) -> httpx.Request:
        """Perform enterprise authorization flow.

        Overrides parent method to use token exchange + JWT bearer grant
        instead of standard authorization code flow.

        This method:
        1. Exchanges IDP ID token for ID-JAG at the IDP server (direct HTTP call)
        2. Returns an httpx.Request for JWT bearer grant (ID-JAG → Access token)

        Returns:
            httpx.Request for the JWT bearer grant to the MCP authorization server
        """
        # Check if we already have valid tokens
        if self.context.is_token_valid():
            # Reuse unexpired cached ID-JAG to prevent auth failures
            if self._id_jag and self._id_jag_expiry:
                if time.time() < self._id_jag_expiry:
                    logger.debug("Reusing cached ID-JAG for JWT bearer grant")
                    return await self.exchange_id_jag_for_access_token(self._id_jag)
                else:
                    logger.debug("Cached ID-JAG expired, will obtain a new one")
            # Fall through to full flow if ID-JAG is expired or missing (e.g., loaded from storage)

        # Step 1: Exchange IDP ID token for ID-JAG (RFC 8693)
        # This is an external call to the IDP, so we make it directly
        async with httpx.AsyncClient(timeout=self.context.timeout) as client:
            id_jag = await self.exchange_token_for_id_jag(client)
            # Cache the ID-JAG for potential reuse
            self._id_jag = id_jag

        # Step 2: Build JWT bearer grant request (RFC 7523)
        # This request will be yielded by the parent's async_auth_flow
        # and the response will be handled by _handle_token_response
        jwt_bearer_request = await self.exchange_id_jag_for_access_token(id_jag)

        logger.debug("Returning JWT bearer grant request to async_auth_flow")
        return jwt_bearer_request

    async def refresh_with_new_id_token(self, new_id_token: str) -> None:
        """Refresh MCP server access tokens using a fresh ID token from the IdP.

        Updates the subject token and clears cached tokens (including ID-JAG),
        triggering re-authentication on the next API request.

        Note: OAuth metadata is not re-discovered. If the MCP server's OAuth
        configuration has changed, you must create a new provider instance.

        Args:
            new_id_token: Fresh ID token obtained from your enterprise IdP.
        """
        logger.info("Refreshing tokens with new ID token from IdP")
        self.token_exchange_params.subject_token = new_id_token

        # Clear caches to force ID-JAG re-exchange and re-authentication
        self._id_jag = None
        self._id_jag_expiry = None
        self.context.clear_tokens()
        logger.debug("Token refresh prepared - will re-authenticate on next request")


def decode_id_jag(id_jag: str) -> IDJAGClaims:
    """Decode an ID-JAG token without verification.

    Args:
        id_jag: The ID-JAG token string

    Returns:
        Decoded ID-JAG claims

    Note:
        This function does not verify the JWT, instead relying on the receiving server to validate it.
    """
    # Decode without verification for inspection
    claims = jwt.decode(id_jag, options={"verify_signature": False})
    header = jwt.get_unverified_header(id_jag)

    # Add typ from header to claims
    claims["typ"] = header.get("typ", "")

    return IDJAGClaims.model_validate(claims)


def validate_token_exchange_params(
    params: TokenExchangeParameters,
) -> None:
    """Validate token exchange parameters.

    Args:
        params: Token exchange parameters to validate

    Raises:
        OAuthFlowError: If parameters are invalid
    """
    if not params.subject_token:
        raise OAuthFlowError("subject_token is required")

    if not params.audience:
        raise OAuthFlowError("audience is required")

    if not params.resource:
        raise OAuthFlowError("resource is required")

    if params.subject_token_type not in [
        "urn:ietf:params:oauth:token-type:id_token",
        "urn:ietf:params:oauth:token-type:saml2",
    ]:
        raise OAuthFlowError(f"Invalid subject_token_type: {params.subject_token_type}")
