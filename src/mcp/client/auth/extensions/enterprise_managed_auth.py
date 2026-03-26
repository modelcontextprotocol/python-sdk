"""Enterprise Managed Authorization extension for MCP (SEP-990).

Implements RFC 8693 Token Exchange and RFC 7523 JWT Bearer Grant for
enterprise SSO integration.
"""

import logging
from json import JSONDecodeError

import httpx
import jwt
from pydantic import BaseModel, Field, ValidationError
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
    """Claims structure for Identity Assertion JWT Authorization Grant.

    Note: ``typ`` is sourced from the JWT *header* (not the payload) by
    ``decode_id_jag``.  It is included here for convenience so callers
    can inspect the full ID-JAG structure from a single object.
    """

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
    - SAFE: Concurrent requests within a single asyncio event loop. Token
      operations are protected by the parent class's ``OAuthContext.lock``
      via ``async_auth_flow``.
    - UNSAFE: Sharing a provider instance across multiple OS threads. Each
      thread must instantiate its own provider and event loop.
    - Note: Ensure any shared ``TokenStorage`` implementation is async-safe.
    """

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
        override_audience_with_issuer: bool = True,
    ) -> None:
        """Initialize Enterprise Auth OAuth Client.

        Args:
            server_url: MCP server URL
            client_metadata: OAuth client metadata
            storage: Token storage implementation
            idp_token_endpoint: Enterprise IdP token endpoint URL
            token_exchange_params: Token exchange parameters (not mutated)
            timeout: Request timeout in seconds
            idp_client_id: Optional client ID registered with the IdP for token exchange
            idp_client_secret: Optional client secret registered with the IdP.
                Must be accompanied by ``idp_client_id``; providing a secret
                without an ID raises ``ValueError``.
            override_audience_with_issuer: If True (default), replaces the IdP
                audience with the discovered OAuth issuer URL. Set to False for
                federated identity setups where the audience must differ.

        Raises:
            ValueError: If ``idp_client_secret`` is provided without ``idp_client_id``.
            OAuthFlowError: If ``token_exchange_params`` fail validation.
        """
        # Validate pure parameters before creating any state (fail-fast)
        if idp_client_secret is not None and idp_client_id is None:
            raise ValueError(
                "idp_client_secret was provided without idp_client_id. Provide both together, or omit the secret."
            )
        validate_token_exchange_params(token_exchange_params)

        super().__init__(
            server_url=server_url,
            client_metadata=client_metadata,
            storage=storage,
            timeout=timeout,
        )
        self.idp_token_endpoint = idp_token_endpoint
        # Keep original params immutable; track mutable subject_token separately
        self.token_exchange_params = token_exchange_params
        self._subject_token = token_exchange_params.subject_token
        self.idp_client_id = idp_client_id
        self.idp_client_secret = idp_client_secret
        self.override_audience_with_issuer = override_audience_with_issuer

    async def exchange_token_for_id_jag(
        self,
        client: httpx.AsyncClient,
    ) -> str:
        """Exchange ID Token for ID-JAG using RFC 8693 Token Exchange.

        Args:
            client: HTTP client for making requests

        Returns:
            The ID-JAG token string

        Raises:
            OAuthTokenError: If token exchange fails
        """
        logger.debug("Starting token exchange for ID-JAG")

        audience = self.token_exchange_params.audience
        if self.override_audience_with_issuer:
            # OAuthMetadata.issuer is a required AnyHttpUrl field (RFC 8414),
            # so it is always non-None when oauth_metadata is present.
            if self.context.oauth_metadata:
                discovered_issuer = str(self.context.oauth_metadata.issuer)
                if audience != discovered_issuer:
                    logger.warning(
                        f"Overriding audience '{audience}' with discovered issuer "
                        f"'{discovered_issuer}'. To prevent this, pass "
                        f"override_audience_with_issuer=False."
                    )
                audience = discovered_issuer

        token_data: TokenExchangeRequestData = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "requested_token_type": self.token_exchange_params.requested_token_type,
            "audience": audience,
            "resource": self.token_exchange_params.resource,
            "subject_token": self._subject_token,
            "subject_token_type": self.token_exchange_params.subject_token_type,
        }

        if self.token_exchange_params.scope and self.token_exchange_params.scope.strip():
            token_data["scope"] = self.token_exchange_params.scope

        # Add IdP client authentication if provided.
        # Sent as POST body parameters (not HTTP Basic) because this is the
        # IdP's token-exchange endpoint — most enterprise IdPs (Okta, Azure AD,
        # Ping) accept body credentials for token exchange.  HTTP Basic is
        # allowed by RFC 6749 §2.3.1 but not universally required here.
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
                    pass

                error: str = error_data.get("error", "unknown_error")
                error_description: str = error_data.get(
                    "error_description", f"Token exchange failed (HTTP {response.status_code})"
                )
                raise OAuthTokenError(f"Token exchange failed: {error} - {error_description}")

            token_response = IDJAGTokenExchangeResponse.model_validate_json(response.content)

            if token_response.issued_token_type != "urn:ietf:params:oauth:token-type:id-jag":
                raise OAuthTokenError(f"Unexpected token type: {token_response.issued_token_type}")

            if token_response.token_type != "N_A":
                logger.warning(f"Expected token_type 'N_A', got '{token_response.token_type}'")

            logger.debug("Successfully obtained ID-JAG")

            return token_response.id_jag

        except httpx.HTTPError as e:
            raise OAuthTokenError(f"HTTP error during token exchange: {e}") from e
        except ValidationError as e:
            raise OAuthTokenError("Invalid token exchange response from IdP") from e

    async def exchange_id_jag_for_access_token(
        self,
        id_jag: str,
    ) -> httpx.Request:
        """Build a JWT bearer grant request to exchange an ID-JAG for an access token (RFC 7523).

        This method only *builds* the ``httpx.Request``; it does not execute
        it.  HTTP execution and error parsing are deferred to the parent
        class's ``async_auth_flow`` via ``_handle_token_response``.

        Follows the same pattern as ``ClientCredentialsOAuthProvider._exchange_token_client_credentials``
        and ``RFC7523OAuthClientProvider._exchange_token_jwt_bearer``:
        use ``_get_token_endpoint()`` for the URL and ``prepare_token_auth()``
        for client authentication — no manual ``client_id`` injection or
        context swapping needed.

        Args:
            id_jag: The ID-JAG token obtained from ``exchange_token_for_id_jag``

        Returns:
            An ``httpx.Request`` for the JWT bearer grant
        """
        logger.debug("Building JWT bearer grant request for ID-JAG")

        token_data: dict[str, str] = {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": id_jag,
        }

        headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}

        # Delegate client authentication (client_secret_basic, client_secret_post,
        # or none) to the parent's context helper — same as every other grant type.
        token_data, headers = self.context.prepare_token_auth(token_data, headers)

        # Include resource parameter per RFC 8707 — same guard as every sibling provider
        if self.context.should_include_resource_param(self.context.protocol_version):
            token_data["resource"] = self.context.get_resource_url()

        # Include scope if configured (may have been updated by parent's async_auth_flow
        # from the server's WWW-Authenticate header before _perform_authorization is called)
        if self.context.client_metadata.scope:
            token_data["scope"] = self.context.client_metadata.scope

        token_url = self._get_token_endpoint()
        return httpx.Request("POST", token_url, data=token_data, headers=headers)

    async def _perform_authorization(self) -> httpx.Request:
        """Perform enterprise authorization flow.

        Called by the parent's ``async_auth_flow`` when a new access token is needed.
        Unconditionally performs full token exchange as the parent already handles
        token validity checks.

        Flow:
        1. Exchange IdP subject token for ID-JAG (RFC 8693, direct HTTP call)
        2. Return an ``httpx.Request`` for the JWT bearer grant (RFC 7523)
           that the parent will execute and pass to ``_handle_token_response``

        Returns:
            httpx.Request for the JWT bearer grant to the MCP authorization server
        """
        # Step 1: Exchange IDP subject token for ID-JAG (RFC 8693)
        async with httpx.AsyncClient(timeout=self.context.timeout) as client:
            id_jag = await self.exchange_token_for_id_jag(client)

        # Step 2: Build JWT bearer grant request (RFC 7523)
        jwt_bearer_request = await self.exchange_id_jag_for_access_token(id_jag)

        logger.debug("Returning JWT bearer grant request to async_auth_flow")
        return jwt_bearer_request

    async def refresh_with_new_id_token(self, new_id_token: str) -> None:
        """Refresh MCP server access tokens using a fresh ID token from the IdP.

        Updates the subject token and clears cached state so that the next API
        request triggers a full re-authentication.  Acquires the context lock
        to prevent racing with an in-progress ``async_auth_flow``.

        Note: OAuth metadata is not re-discovered. If the MCP server's OAuth
        configuration has changed, create a new provider instance instead.

        Warning: This method is NOT safe to call from a different OS thread.
        Call it only from the same thread and event loop that owns this
        provider instance.

        Args:
            new_id_token: Fresh ID token obtained from your enterprise IdP.
        """
        async with self.context.lock:
            logger.info("Refreshing tokens with new ID token from IdP")
            # Update the mutable subject token (does NOT mutate the original params object)
            self._subject_token = new_id_token

            # Clear tokens to force full re-exchange on next request
            self.context.clear_tokens()
            logger.debug("Token refresh prepared — will re-authenticate on next request")


def decode_id_jag(id_jag: str) -> IDJAGClaims:
    """Decode an ID-JAG token without verification.

    Relies on the receiving server to validate the JWT signature.

    Args:
        id_jag: The ID-JAG token string

    Returns:
        Decoded ID-JAG claims
    """
    claims = jwt.decode(id_jag, options={"verify_signature": False})
    header = jwt.get_unverified_header(id_jag)
    claims["typ"] = header.get("typ", "")

    return IDJAGClaims.model_validate(claims)


def validate_token_exchange_params(
    params: TokenExchangeParameters,
) -> None:
    """Validate token exchange parameters beyond Pydantic field constraints.

    Pydantic ``Field(...)`` rejects *missing* values but permits empty strings.
    This function adds:
    - Empty-string checks for ``subject_token``, ``audience``, ``resource``
    - Allow-list check for ``subject_token_type`` (id_token or saml2)

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

    if params.subject_token_type not in {
        "urn:ietf:params:oauth:token-type:id_token",
        "urn:ietf:params:oauth:token-type:saml2",
    }:
        raise OAuthFlowError(f"Invalid subject_token_type: {params.subject_token_type}")
