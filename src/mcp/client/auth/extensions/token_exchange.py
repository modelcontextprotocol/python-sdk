"""OAuth 2.0 Token Exchange (RFC 8693) client provider for MCP.

Provides `TokenExchangeOAuthProvider`, which exchanges a security token issued by an
enterprise identity provider for an MCP access token at the MCP authorization server's
token endpoint. This is the client side of SEP-990 (enterprise IdP policy controls): the
client first obtains an Identity Assertion Authorization Grant (ID-JAG) from the IdP, then
exchanges it here for a token usable against the MCP server.

Obtaining the ID-JAG (logging into the IdP and performing the first token exchange against
it) is deployment-specific and out of scope for the SDK. The caller supplies it through the
`subject_token_provider` callback, which receives the MCP authorization server's issuer
identifier as its audience and returns the security token to exchange.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Literal

import httpx

from mcp.client.auth import OAuthClientProvider, OAuthFlowError, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata

TOKEN_EXCHANGE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
JWT_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:jwt"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"


class TokenExchangeOAuthProvider(OAuthClientProvider):
    """OAuth provider for the RFC 8693 token-exchange grant.

    Exchanges a subject token (for SEP-990, the IdP-issued ID-JAG) for an MCP access token,
    bypassing the interactive authorization-code flow and dynamic client registration. The
    subject token is fetched lazily from `subject_token_provider` so a fresh token is used on
    each exchange.

    Example:
        ```python
        async def fetch_id_jag(audience: str) -> str:
            # `audience` is the MCP authorization server's issuer identifier; the returned
            # ID-JAG must carry that as its `aud` claim. How the ID-JAG is obtained from the
            # enterprise IdP is deployment-specific and not handled by the SDK.
            return await my_idp.exchange_id_token_for_id_jag(audience=audience)


        provider = TokenExchangeOAuthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=my_token_storage,
            client_id="my-client-id",
            subject_token_provider=fetch_id_jag,
        )
        ```
    """

    def __init__(
        self,
        server_url: str,
        storage: TokenStorage,
        client_id: str,
        subject_token_provider: Callable[[str], Awaitable[str]],
        subject_token_type: str = JWT_TOKEN_TYPE,
        requested_token_type: str | None = ACCESS_TOKEN_TYPE,
        scopes: str | None = None,
        client_secret: str | None = None,
        token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post"] = "client_secret_post",
    ) -> None:
        """Initialize the token-exchange OAuth provider.

        Args:
            server_url: The MCP server URL.
            storage: Token storage implementation.
            client_id: The OAuth client ID registered with the MCP authorization server.
            subject_token_provider: Async callback that takes the authorization server's
                issuer identifier (the audience) and returns the subject token to exchange
                (the ID-JAG for SEP-990).
            subject_token_type: RFC 8693 type identifier of the subject token. Defaults to
                `urn:ietf:params:oauth:token-type:jwt`, the type of an ID-JAG.
            requested_token_type: RFC 8693 desired type of the issued token. Defaults to
                `urn:ietf:params:oauth:token-type:access_token`, since SEP-990 yields an MCP
                access token; pass `None` to omit the parameter.
            scopes: Optional space-separated list of scopes to request.
            client_secret: Optional client secret. When set, the request authenticates as a
                confidential client using `token_endpoint_auth_method`; otherwise the public
                client form is used and the method is `none`.
            token_endpoint_auth_method: Authentication method when `client_secret` is set.
                Either `client_secret_post` (default) or `client_secret_basic`.
        """
        auth_method = token_endpoint_auth_method if client_secret is not None else "none"
        client_metadata = OAuthClientMetadata(
            redirect_uris=None,
            grant_types=[TOKEN_EXCHANGE_GRANT_TYPE],
            token_endpoint_auth_method=auth_method,
            scope=scopes,
        )
        super().__init__(server_url, client_metadata, storage, None, None, 300.0)
        self._subject_token_provider = subject_token_provider
        self._subject_token_type = subject_token_type
        self._requested_token_type = requested_token_type
        self._fixed_client_info = OAuthClientInformationFull(
            redirect_uris=None,
            client_id=client_id,
            client_secret=client_secret,
            grant_types=[TOKEN_EXCHANGE_GRANT_TYPE],
            token_endpoint_auth_method=auth_method,
            scope=scopes,
        )

    async def _initialize(self) -> None:
        """Load stored tokens and set pre-configured client_info."""
        self.context.current_tokens = await self.context.storage.get_tokens()
        self.context.client_info = self._fixed_client_info
        self._initialized = True

    async def _perform_authorization(self) -> httpx.Request:
        """Perform the token-exchange grant."""
        return await self._exchange_token()

    async def _exchange_token(self) -> httpx.Request:
        """Build the RFC 8693 token-exchange request."""
        if not self.context.oauth_metadata:
            raise OAuthFlowError("Missing OAuth metadata for token exchange")  # pragma: no cover
        if not self.context.client_info:
            raise OAuthFlowError("Missing client info for token exchange")  # pragma: no cover

        audience = str(self.context.oauth_metadata.issuer)
        subject_token = await self._subject_token_provider(audience)

        token_data: dict[str, Any] = {
            "grant_type": TOKEN_EXCHANGE_GRANT_TYPE,
            "subject_token": subject_token,
            "subject_token_type": self._subject_token_type,
            "client_id": self.context.client_info.client_id,
        }
        if self._requested_token_type is not None:
            token_data["requested_token_type"] = self._requested_token_type

        headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}
        token_data, headers = self.context.prepare_token_auth(token_data, headers)

        if self.context.should_include_resource_param(self.context.protocol_version):
            token_data["resource"] = self.context.get_resource_url()

        if self.context.client_metadata.scope:
            token_data["scope"] = self.context.client_metadata.scope

        token_url = self._get_token_endpoint()
        return httpx.Request("POST", token_url, data=token_data, headers=headers)
