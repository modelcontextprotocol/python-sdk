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

SEP-990 §5.1 requires the client to authenticate; this SDK currently requires a shared secret, so
`client_secret` is mandatory (the spec also permits e.g. `private_key_jwt`). The target
authorization server is pinned via `expected_issuer`: the provider fixes authorization-server
discovery to that issuer and refuses to send the ID-JAG or client secret to any other, preventing a
hostile resource server from redirecting the credentials elsewhere.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from mcp.client.auth import OAuthClientProvider, OAuthFlowError, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, ProtectedResourceMetadata

JWT_BEARER_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"


_DEFAULT_PORTS = {"https": 443, "http": 80}


def _origin(url: str) -> tuple[str, str, int | None]:
    """Return the (scheme, host, port) origin of a URL for same-origin comparison.

    The port is normalized to the scheme's default so an explicit `:443`/`:80` compares equal to the
    same origin written without a port.
    """
    parsed = urlsplit(url)
    port = parsed.port if parsed.port is not None else _DEFAULT_PORTS.get(parsed.scheme)
    return (parsed.scheme, parsed.hostname or "", port)


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

        Raises:
            ValueError: If `client_secret` or `expected_issuer` is empty.
        """
        if not client_secret:
            raise ValueError("client_secret is required: SEP-990 mandates a confidential client")
        if not expected_issuer:
            raise ValueError("expected_issuer is required to pin the authorization server")
        client_metadata = OAuthClientMetadata(
            redirect_uris=None,
            grant_types=[JWT_BEARER_GRANT_TYPE],
            token_endpoint_auth_method=token_endpoint_auth_method,
            scope=scopes,
        )
        super().__init__(server_url, client_metadata, storage, None, None, 300.0)
        self._assertion_provider = assertion_provider
        self._expected_issuer = expected_issuer
        # The caller's requested scope, sent verbatim on every exchange. The base flow's
        # scope-selection step overwrites `client_metadata.scope` with server-advertised scopes;
        # `_exchange_assertion` ignores that and uses this so the request is never broadened.
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
        # Pin the authorization server up front: the base flow otherwise takes the AS from the
        # (untrusted) resource server's PRM / fetches ASM from the RS origin on the legacy path,
        # where validate_metadata_issuer is skipped. Setting auth_server_url makes ASM discovery
        # target the expected AS's well-known and run validate_metadata_issuer, so a hostile RS
        # cannot forge a metadata document pointing the credentials elsewhere.
        self.context.auth_server_url = self._expected_issuer
        self._initialized = True

    async def _validate_resource_match(self, prm: ProtectedResourceMetadata) -> None:
        """Reject a PRM that names an authorization server other than the pinned one.

        On the PRM path the base flow would adopt `prm.authorization_servers[0]` as the AS and,
        if it differs from the bound credentials, discard them and attempt DCR against it. Refusing
        an unexpected AS here stops that before any client metadata is disclosed.
        """
        await super()._validate_resource_match(prm)
        servers = [str(s) for s in prm.authorization_servers]
        if self._expected_issuer not in servers:
            raise OAuthFlowError(
                f"Protected resource names authorization servers {servers}, not the expected {self._expected_issuer}"
            )

    async def _perform_authorization(self) -> httpx.Request:
        """Perform the jwt-bearer grant with the ID-JAG."""
        return await self._exchange_assertion()

    async def _exchange_assertion(self) -> httpx.Request:
        """Build the RFC 7523 jwt-bearer token request carrying the ID-JAG."""
        if not self.context.oauth_metadata:
            # Reachable when both PRM and ASM discovery 404 (legacy server): the pinned client_info
            # skips registration, so the flow reaches here with no metadata.
            raise OAuthFlowError("Missing OAuth metadata for identity assertion grant")
        if not self.context.client_info:
            raise OAuthFlowError("Missing client info for identity assertion grant")  # pragma: no cover

        # Pin the authorization server: both its metadata issuer AND the token endpoint the
        # credentials are POSTed to are discovered via the (untrusted) resource server. Checking the
        # issuer alone is not enough - on the legacy no-PRM path a hostile RS can serve the expected
        # issuer with an attacker-controlled token_endpoint. Require both to be on the expected
        # issuer's origin before releasing the ID-JAG or secret.
        issuer = str(self.context.oauth_metadata.issuer)
        if issuer != self._expected_issuer:
            raise OAuthFlowError(
                f"Authorization server issuer {issuer} does not match expected {self._expected_issuer}"
            )
        token_url = self._get_token_endpoint()
        if _origin(token_url) != _origin(self._expected_issuer):
            raise OAuthFlowError(
                f"Token endpoint {token_url} is not on the expected issuer origin {self._expected_issuer}"
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

        # Always send exactly the caller's configured scope. The base 401 scope-selection step (and
        # the 403 step-up union) overwrite client_metadata.scope with server-advertised scopes; this
        # provider must never broaden the request with them. SEP-990's model is that the AS derives
        # the granted scope from the validated ID-JAG and policy, so client-driven scope escalation
        # does not apply - a broader grant comes from re-issuing the ID-JAG, not requesting more
        # here. Write the configured value back so the base _handle_token_response RFC 6749 §5.1
        # backfill records it (not the server-advertised set) on the stored token.
        self.context.client_metadata.scope = self._scopes
        if self._scopes:
            token_data["scope"] = self._scopes

        return httpx.Request("POST", token_url, data=token_data, headers=headers)
