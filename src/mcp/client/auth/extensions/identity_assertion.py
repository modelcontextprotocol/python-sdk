"""SEP-990 Identity Assertion Authorization Grant (RFC 7523 jwt-bearer) client provider.

`IdentityAssertionOAuthProvider` is the client side of SEP-990 leg 2: it presents an Identity
Assertion Authorization Grant (ID-JAG) - a signed JWT issued by the enterprise identity provider -
to the MCP authorization server's token endpoint using the RFC 7523 jwt-bearer grant
(`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, ID-JAG as `assertion`), and receives an
MCP access token.

The authorization server is configuration, not discovery. SEP-990's trust model is the inverse of
the default OAuth client's: the AS issuer is supplied at construction, authorization-server metadata
is fetched from that issuer's own RFC 8414 well-known, and the resource server is never asked which
AS to use - so it cannot redirect the ID-JAG or client secret elsewhere. There is no protected
resource metadata fetch, no dynamic client registration, and no server-driven scope selection.

Obtaining the ID-JAG (logging into the IdP and the leg-1 token exchange against it) is
deployment-specific and out of scope for the SDK. The caller supplies it through the
`assertion_provider` callback, which receives the configured issuer (the `aud` the ID-JAG must
carry) and the MCP server's resource identifier (the `resource` claim it must carry, per ext-auth
section 4.3), and returns the ID-JAG.
"""

import base64
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Literal
from urllib.parse import quote, urlsplit

import anyio
import httpx

from mcp.client.auth import OAuthFlowError, OAuthTokenError, TokenStorage
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    create_oauth_metadata_request,
    extract_field_from_www_auth,
    extract_scope_from_www_auth,
    handle_auth_metadata_response,
    handle_token_response_scopes,
    union_scopes,
    validate_metadata_issuer,
)
from mcp.shared._httpx_utils import redirect_error
from mcp.shared.auth import JWT_BEARER_GRANT_TYPE, OAuthClientInformationFull, OAuthToken
from mcp.shared.auth_utils import calculate_token_expiry, resource_url_from_server_url

_DEFAULT_PORTS = {"https": 443, "http": 80}


def _origin(url: str) -> tuple[str, str, int | None]:
    """Return the (scheme, host, port) origin of a URL for same-origin comparison.

    The port is normalized to the scheme's default so an explicit `:443`/`:80` compares equal to the
    same origin written without a port.
    """
    parsed = urlsplit(url)
    port = parsed.port if parsed.port is not None else _DEFAULT_PORTS.get(parsed.scheme)
    return (parsed.scheme, parsed.hostname or "", port)


class IdentityAssertionOAuthProvider(httpx.Auth):
    """`httpx.Auth` for the SEP-990 ID-JAG flow (RFC 7523 jwt-bearer grant) against a configured AS.

    The authorization server `issuer` is fixed at construction; metadata is fetched from its
    RFC 8414 well-known and the ID-JAG and client secret are sent only to that issuer's token
    endpoint. The resource server is never consulted for AS selection. The ID-JAG is fetched lazily
    from `assertion_provider` so a fresh assertion is used on each exchange.

    Example:
        ```python
        async def fetch_id_jag(audience: str, resource: str) -> str:
            # `audience` is the configured issuer (the ID-JAG `aud`); `resource` is the MCP
            # server's identifier (the ID-JAG `resource` claim). Obtaining the ID-JAG from the
            # enterprise IdP is deployment-specific and not handled by the SDK.
            return await my_idp.issue_id_jag(audience=audience, resource=resource)


        provider = IdentityAssertionOAuthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=my_token_storage,
            client_id="my-client-id",
            client_secret="my-client-secret",
            issuer="https://auth.example.com",
            assertion_provider=fetch_id_jag,
        )
        ```
    """

    requires_response_body = True

    def __init__(
        self,
        server_url: str,
        storage: TokenStorage,
        client_id: str,
        client_secret: str,
        issuer: str,
        assertion_provider: Callable[[str, str], Awaitable[str]],
        scope: str | None = None,
        token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post"] = "client_secret_post",
    ) -> None:
        """Initialize the identity-assertion OAuth provider.

        Args:
            server_url: The MCP server URL.
            storage: Token storage implementation.
            client_id: The OAuth client ID registered with the MCP authorization server.
            client_secret: The client secret. SEP-990 section 5.1 requires a confidential client.
            issuer: The issuer identifier of the MCP authorization server this client is provisioned
                for. Authorization-server metadata is fetched from this issuer's well-known and the
                ID-JAG and secret are sent only to its token endpoint.
            assertion_provider: Async callback taking `(audience, resource)` - the configured issuer
                and the MCP server's resource identifier - and returning the ID-JAG.
            scope: Optional space-separated list of scopes to request.
            token_endpoint_auth_method: Confidential-client auth method, either `client_secret_post`
                (default) or `client_secret_basic`.
        """
        if not client_secret:
            raise ValueError("client_secret is required: SEP-990 mandates a confidential client")
        if not issuer:
            raise ValueError("issuer is required: the authorization server is configuration, not discovery")
        self._resource = resource_url_from_server_url(server_url)
        self._storage = storage
        self._issuer = issuer
        self._assertion_provider = assertion_provider
        self._scope = scope
        self._client = OAuthClientInformationFull(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uris=None,
            grant_types=[JWT_BEARER_GRANT_TYPE],
            token_endpoint_auth_method=token_endpoint_auth_method,
            issuer=issuer,
        )
        self._token_endpoint: str | None = None
        self._tokens: OAuthToken | None = None
        self._expiry: float | None = None
        self._lock = anyio.Lock()
        self._initialized = False

    def _build_token_request(self, scope: str | None, assertion: str) -> httpx.Request:
        """Build the RFC 7523 jwt-bearer token request, applying confidential-client auth."""
        assert self._token_endpoint is not None
        assert self._client.client_id is not None and self._client.client_secret is not None
        data: dict[str, str] = {
            "grant_type": JWT_BEARER_GRANT_TYPE,
            "assertion": assertion,
            "client_id": self._client.client_id,
            "resource": self._resource,
        }
        if scope:
            data["scope"] = scope
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if self._client.token_endpoint_auth_method == "client_secret_basic":
            # RFC 6749 section 2.3.1: URL-encode each part, then base64 the colon-joined pair.
            encoded_id = quote(self._client.client_id, safe="")
            encoded_secret = quote(self._client.client_secret, safe="")
            credentials = base64.b64encode(f"{encoded_id}:{encoded_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
        else:
            data["client_secret"] = self._client.client_secret
        return httpx.Request("POST", self._token_endpoint, data=data, headers=headers)

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        async with self._lock:
            if not self._initialized:
                self._tokens = await self._storage.get_tokens()
                self._expiry = calculate_token_expiry(self._tokens.expires_in) if self._tokens else None
                self._initialized = True

            if self._tokens and (self._expiry is None or time.time() <= self._expiry):
                request.headers["Authorization"] = f"Bearer {self._tokens.access_token}"
            response = yield request

            if response.status_code == 401:
                scope_to_request = self._scope
            elif response.status_code == 403 and extract_field_from_www_auth(response, "error") == "insufficient_scope":
                scope_to_request = union_scopes(self._scope, extract_scope_from_www_auth(response))
            else:
                return

            # Discover ASM from the configured issuer's well-known. The RS is not consulted: both
            # arguments are the issuer, so even the helper's legacy fallback resolves there.
            if self._token_endpoint is None:
                for url in build_oauth_authorization_server_metadata_discovery_urls(self._issuer, self._issuer):
                    asm_response = yield create_oauth_metadata_request(url)
                    ok, asm = await handle_auth_metadata_response(asm_response)
                    if not ok:
                        break
                    if asm is not None:
                        validate_metadata_issuer(asm, self._issuer)
                        token_endpoint = str(asm.token_endpoint)
                        if _origin(token_endpoint) != _origin(self._issuer):
                            raise OAuthFlowError(
                                f"Token endpoint {token_endpoint} is not on the configured issuer origin {self._issuer}"
                            )
                        self._token_endpoint = token_endpoint
                        break
                if self._token_endpoint is None:
                    raise OAuthFlowError(f"No authorization server metadata at configured issuer {self._issuer}")

            assertion = await self._assertion_provider(self._issuer, self._resource)
            token_response = yield self._build_token_request(scope_to_request, assertion)
            if token_response.has_redirect_location:
                raise redirect_error(token_response, context="OAuth token exchange request")
            if token_response.status_code != 200:
                body = (await token_response.aread()).decode(errors="replace")
                raise OAuthTokenError(f"Token exchange failed ({token_response.status_code}): {body}")
            tokens = await handle_token_response_scopes(token_response)
            if tokens.scope is None:
                tokens.scope = scope_to_request
            self._tokens = tokens
            self._expiry = calculate_token_expiry(tokens.expires_in)
            await self._storage.set_tokens(tokens)

            request.headers["Authorization"] = f"Bearer {tokens.access_token}"
            yield request
