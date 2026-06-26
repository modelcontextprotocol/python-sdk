"""SEP-990 Identity Assertion Authorization Grant (RFC 7523 jwt-bearer) client provider.

Provides `IdentityAssertionOAuthProvider`, the client side of SEP-990 leg 2: it presents an
Identity Assertion Authorization Grant (ID-JAG) - a signed JWT issued by the enterprise identity
provider - to the MCP authorization server's token endpoint using the RFC 7523 jwt-bearer grant
(`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, ID-JAG as `assertion`), and receives an
MCP access token.

Obtaining the ID-JAG (logging into the IdP and the leg-1 token exchange against it) is
deployment-specific and out of scope for the SDK. The caller supplies it through the
`assertion_provider` callback, which receives the MCP authorization server's issuer (the `aud` the
ID-JAG must carry) and the MCP server's resource identifier (the `resource` the ID-JAG must carry,
per ext-auth §4.3), and returns the ID-JAG.

SEP-990 §5.1 requires a confidential client, so a `client_secret` is mandatory. The target
authorization server is pinned via `expected_issuer`: the provider refuses to send the ID-JAG or
client secret unless the issuer discovered from the (resource-server-controlled) metadata matches,
preventing a hostile resource server from redirecting the credentials elsewhere.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Literal

import httpx

from mcp.client.auth import OAuthClientProvider, OAuthFlowError, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata

JWT_BEARER_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"


class IdentityAssertionOAuthProvider(OAuthClientProvider):
    """OAuth provider for the SEP-990 ID-JAG flow (RFC 7523 jwt-bearer grant).

    Presents an ID-JAG as the `assertion` of a jwt-bearer token request, bypassing the
    interactive authorization-code flow and dynamic client registration. The ID-JAG is fetched
    lazily from `assertion_provider` so a fresh assertion is used on each exchange.

    Example:
        ```python
        async def fetch_id_jag(audience: str, resource: str) -> str:
            # `audience` is the MCP authorization server's issuer (the ID-JAG `aud`); `resource`
            # is the MCP server's identifier (the ID-JAG `resource` claim). Obtaining the ID-JAG
            # from the enterprise IdP is deployment-specific and not handled by the SDK.
            return await my_idp.issue_id_jag(audience=audience, resource=resource)


        provider = IdentityAssertionOAuthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=my_token_storage,
            client_id="my-client-id",
            client_secret="my-client-secret",
            expected_issuer="https://auth.example.com",
            assertion_provider=fetch_id_jag,
        )
        ```
    """

    def __init__(
        self,
        server_url: str,
        storage: TokenStorage,
        client_id: str,
        client_secret: str,
        expected_issuer: str,
        assertion_provider: Callable[[str, str], Awaitable[str]],
        scopes: str | None = None,
        token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post"] = "client_secret_post",
    ) -> None:
        """Initialize the identity-assertion OAuth provider.

        Args:
            server_url: The MCP server URL.
            storage: Token storage implementation.
            client_id: The OAuth client ID registered with the MCP authorization server.
            client_secret: The client secret. SEP-990 §5.1 requires a confidential client.
            expected_issuer: The issuer identifier of the MCP authorization server this client is
                provisioned for. The provider refuses to send the ID-JAG or secret unless the
                discovered metadata issuer matches this value.
            assertion_provider: Async callback taking `(audience, resource)` - the authorization
                server's issuer and the MCP server's resource identifier - and returning the ID-JAG.
            scopes: Optional space-separated list of scopes to request. Sent verbatim on the
                exchange; not overridden by server-advertised scopes.
            token_endpoint_auth_method: Confidential-client auth method, either
                `client_secret_post` (default) or `client_secret_basic`.
        """
        client_metadata = OAuthClientMetadata(
            redirect_uris=None,
            grant_types=[JWT_BEARER_GRANT_TYPE],
            token_endpoint_auth_method=token_endpoint_auth_method,
            scope=scopes,
        )
        super().__init__(server_url, client_metadata, storage, None, None, 300.0)
        self._assertion_provider = assertion_provider
        self._expected_issuer = expected_issuer
        # The caller's requested scope, kept verbatim. The base 401 flow's scope-selection step
        # overwrites `client_metadata.scope` with server-advertised scopes, so the request reads
        # this rather than the mutated value to honour what the caller asked for.
        self._scopes = scopes
        self._fixed_client_info = OAuthClientInformationFull(
            redirect_uris=None,
            client_id=client_id,
            client_secret=client_secret,
            grant_types=[JWT_BEARER_GRANT_TYPE],
            token_endpoint_auth_method=token_endpoint_auth_method,
            scope=scopes,
            # SEP-2352 binding: pin these pre-provisioned credentials to the expected AS so the
            # base flow's credentials_match_issuer guard discards them if the discovered AS differs.
            issuer=expected_issuer,
        )

    async def _initialize(self) -> None:
        """Load stored tokens and set pre-configured client_info."""
        self.context.current_tokens = await self.context.storage.get_tokens()
        self.context.client_info = self._fixed_client_info
        self._initialized = True

    async def _perform_authorization(self) -> httpx.Request:
        """Perform the jwt-bearer grant with the ID-JAG."""
        return await self._exchange_assertion()

    async def _exchange_assertion(self) -> httpx.Request:
        """Build the RFC 7523 jwt-bearer token request carrying the ID-JAG."""
        if not self.context.oauth_metadata:
            raise OAuthFlowError("Missing OAuth metadata for identity assertion grant")  # pragma: no cover
        if not self.context.client_info:
            raise OAuthFlowError("Missing client info for identity assertion grant")  # pragma: no cover

        # Pin the authorization server: the metadata issuer is discovered via the resource server,
        # which is untrusted. Refuse to release the ID-JAG or secret to an unexpected AS.
        issuer = str(self.context.oauth_metadata.issuer)
        if issuer != self._expected_issuer:
            raise OAuthFlowError(
                f"Authorization server issuer {issuer} does not match expected {self._expected_issuer}"
            )

        resource = self.context.get_resource_url()
        assertion = await self._assertion_provider(issuer, resource)

        token_data: dict[str, Any] = {
            "grant_type": JWT_BEARER_GRANT_TYPE,
            "assertion": assertion,
            "client_id": self.context.client_info.client_id,
        }

        headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}
        token_data, headers = self.context.prepare_token_auth(token_data, headers)

        if self.context.should_include_resource_param(self.context.protocol_version):
            token_data["resource"] = resource

        if self._scopes:
            token_data["scope"] = self._scopes

        token_url = self._get_token_endpoint()
        return httpx.Request("POST", token_url, data=token_data, headers=headers)
