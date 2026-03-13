"""MCP unified conformance test client.

This client is designed to work with the @modelcontextprotocol/conformance npm package.
It handles all conformance test scenarios via environment variables and CLI arguments.

Contract:
    - MCP_CONFORMANCE_SCENARIO env var -> scenario name
    - MCP_CONFORMANCE_CONTEXT env var -> optional JSON (for auth scenarios)
    - Server URL as last CLI argument (sys.argv[1])
    - Must exit 0 within 30 seconds

Scenarios:
    initialize                              - Connect, initialize, list tools, close
    tools_call                              - Connect, call add_numbers(a=5, b=3), close
    sse-retry                               - Connect, call test_reconnection, close
    elicitation-sep1034-client-defaults     - Elicitation with default accept callback
    auth/client-credentials-jwt             - Client credentials with private_key_jwt
    auth/client-credentials-basic           - Client credentials with client_secret_basic
    auth/cross-app-access-complete-flow     - Enterprise managed OAuth (SEP-990) - v0.1.14+
    auth/enterprise-token-exchange          - Enterprise auth with OIDC ID token (legacy name)
    auth/enterprise-saml-exchange           - Enterprise auth with SAML assertion (legacy name)
    auth/enterprise-id-jag-validation       - Validate ID-JAG token structure (legacy name)
    auth/*                                  - Authorization code flow (default for auth scenarios)

Enterprise Auth (SEP-990):
    The conformance package v0.1.14+ (https://github.com/modelcontextprotocol/conformance/pull/110)
    provides the scenario 'auth/cross-app-access-complete-flow' which tests the complete
    enterprise managed OAuth flow: IDP ID token → ID-JAG → access token.

    The client receives test context (idp_id_token, idp_token_endpoint, etc.) via
    MCP_CONFORMANCE_CONTEXT environment variable and performs the token exchange flows automatically.
"""

import asyncio
import json
import logging
import os
import sys
from collections.abc import Callable, Coroutine
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import AnyUrl

from mcp import ClientSession, types
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.auth.extensions.client_credentials import (
    ClientCredentialsOAuthProvider,
    PrivateKeyJWTOAuthProvider,
    SignedJWTParameters,
)
from mcp.client.context import ClientRequestContext
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

# Set up logging to stderr (stdout is for conformance test output)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# Type for async scenario handler functions
ScenarioHandler = Callable[[str], Coroutine[Any, None, None]]

# Registry of scenario handlers
HANDLERS: dict[str, ScenarioHandler] = {}


def register(name: str) -> Callable[[ScenarioHandler], ScenarioHandler]:
    """Register a scenario handler."""

    def decorator(fn: ScenarioHandler) -> ScenarioHandler:
        HANDLERS[name] = fn
        return fn

    return decorator


def get_conformance_context() -> dict[str, Any]:
    """Load conformance test context from MCP_CONFORMANCE_CONTEXT environment variable."""
    context_json = os.environ.get("MCP_CONFORMANCE_CONTEXT")
    if not context_json:
        raise RuntimeError(
            "MCP_CONFORMANCE_CONTEXT environment variable not set. "
            "Expected JSON with client_id, client_secret, and/or private_key_pem."
        )
    try:
        return json.loads(context_json)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse MCP_CONFORMANCE_CONTEXT as JSON: {e}") from e


class InMemoryTokenStorage(TokenStorage):
    """Simple in-memory token storage for conformance testing."""

    def __init__(self) -> None:
        self._tokens: OAuthToken | None = None
        self._client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info


class ConformanceOAuthCallbackHandler:
    """OAuth callback handler that automatically fetches the authorization URL
    and extracts the auth code, without requiring user interaction.
    """

    def __init__(self) -> None:
        self._auth_code: str | None = None
        self._state: str | None = None

    async def handle_redirect(self, authorization_url: str) -> None:
        """Fetch the authorization URL and extract the auth code from the redirect."""
        logger.debug(f"Fetching authorization URL: {authorization_url}")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                authorization_url,
                follow_redirects=False,
            )

            if response.status_code in (301, 302, 303, 307, 308):
                location = cast(str, response.headers.get("location"))
                if location:
                    redirect_url = urlparse(location)
                    query_params: dict[str, list[str]] = parse_qs(redirect_url.query)

                    if "code" in query_params:
                        self._auth_code = query_params["code"][0]
                        state_values = query_params.get("state")
                        self._state = state_values[0] if state_values else None
                        logger.debug(f"Got auth code from redirect: {self._auth_code[:10]}...")
                        return
                    else:
                        raise RuntimeError(f"No auth code in redirect URL: {location}")
                else:
                    raise RuntimeError(f"No redirect location received from {authorization_url}")
            else:
                raise RuntimeError(f"Expected redirect response, got {response.status_code} from {authorization_url}")

    async def handle_callback(self) -> tuple[str, str | None]:
        """Return the captured auth code and state."""
        if self._auth_code is None:
            raise RuntimeError("No authorization code available - was handle_redirect called?")
        auth_code = self._auth_code
        state = self._state
        self._auth_code = None
        self._state = None
        return auth_code, state


# --- Scenario Handlers ---


@register("initialize")
async def run_initialize(server_url: str) -> None:
    """Connect, initialize, list tools, close."""
    async with streamable_http_client(url=server_url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            logger.debug("Initialized successfully")
            await session.list_tools()
            logger.debug("Listed tools successfully")


@register("tools_call")
async def run_tools_call(server_url: str) -> None:
    """Connect, initialize, list tools, call add_numbers(a=5, b=3), close."""
    async with streamable_http_client(url=server_url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            await session.list_tools()
            result = await session.call_tool("add_numbers", {"a": 5, "b": 3})
            logger.debug(f"add_numbers result: {result}")


@register("sse-retry")
async def run_sse_retry(server_url: str) -> None:
    """Connect, initialize, list tools, call test_reconnection, close."""
    async with streamable_http_client(url=server_url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            await session.list_tools()
            result = await session.call_tool("test_reconnection", {})
            logger.debug(f"test_reconnection result: {result}")


async def default_elicitation_callback(
    context: ClientRequestContext,
    params: types.ElicitRequestParams,
) -> types.ElicitResult | types.ErrorData:
    """Accept elicitation and apply defaults from the schema (SEP-1034)."""
    content: dict[str, str | int | float | bool | list[str] | None] = {}

    # For form mode, extract defaults from the requested_schema
    if isinstance(params, types.ElicitRequestFormParams):
        schema = params.requested_schema
        logger.debug(f"Elicitation schema: {schema}")
        properties = schema.get("properties", {})
        for prop_name, prop_schema in properties.items():
            if "default" in prop_schema:
                content[prop_name] = prop_schema["default"]
        logger.debug(f"Applied defaults: {content}")

    return types.ElicitResult(action="accept", content=content)


@register("elicitation-sep1034-client-defaults")
async def run_elicitation_defaults(server_url: str) -> None:
    """Connect with elicitation callback that applies schema defaults."""
    async with streamable_http_client(url=server_url) as (read_stream, write_stream):
        async with ClientSession(
            read_stream, write_stream, elicitation_callback=default_elicitation_callback
        ) as session:
            await session.initialize()
            await session.list_tools()
            result = await session.call_tool("test_client_elicitation_defaults", {})
            logger.debug(f"test_client_elicitation_defaults result: {result}")


@register("auth/client-credentials-jwt")
async def run_client_credentials_jwt(server_url: str) -> None:
    """Client credentials flow with private_key_jwt authentication."""
    context = get_conformance_context()
    client_id = context.get("client_id")
    private_key_pem = context.get("private_key_pem")
    signing_algorithm = context.get("signing_algorithm", "ES256")

    if not client_id:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'client_id'")
    if not private_key_pem:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'private_key_pem'")

    jwt_params = SignedJWTParameters(
        issuer=client_id,
        subject=client_id,
        signing_algorithm=signing_algorithm,
        signing_key=private_key_pem,
    )

    oauth_auth = PrivateKeyJWTOAuthProvider(
        server_url=server_url,
        storage=InMemoryTokenStorage(),
        client_id=client_id,
        assertion_provider=jwt_params.create_assertion_provider(),
    )

    await _run_auth_session(server_url, oauth_auth)


@register("auth/client-credentials-basic")
async def run_client_credentials_basic(server_url: str) -> None:
    """Client credentials flow with client_secret_basic authentication."""
    context = get_conformance_context()
    client_id = context.get("client_id")
    client_secret = context.get("client_secret")

    if not client_id:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'client_id'")
    if not client_secret:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'client_secret'")

    oauth_auth = ClientCredentialsOAuthProvider(
        server_url=server_url,
        storage=InMemoryTokenStorage(),
        client_id=client_id,
        client_secret=client_secret,
        token_endpoint_auth_method="client_secret_basic",
    )

    await _run_auth_session(server_url, oauth_auth)


async def run_auth_code_client(server_url: str) -> None:
    """Authorization code flow (default for auth/* scenarios)."""
    callback_handler = ConformanceOAuthCallbackHandler()
    storage = InMemoryTokenStorage()

    # Check for pre-registered client credentials from context
    context_json = os.environ.get("MCP_CONFORMANCE_CONTEXT")
    if context_json:
        try:
            context = json.loads(context_json)
            client_id = context.get("client_id")
            client_secret = context.get("client_secret")
            if client_id:
                await storage.set_client_info(
                    OAuthClientInformationFull(
                        client_id=client_id,
                        client_secret=client_secret,
                        redirect_uris=[AnyUrl("http://localhost:3000/callback")],
                        token_endpoint_auth_method="client_secret_basic" if client_secret else "none",
                    )
                )
                logger.debug(f"Pre-loaded client credentials: client_id={client_id}")
        except json.JSONDecodeError:
            logger.exception("Failed to parse MCP_CONFORMANCE_CONTEXT")

    oauth_auth = OAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="conformance-client",
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=storage,
        redirect_handler=callback_handler.handle_redirect,
        callback_handler=callback_handler.handle_callback,
        client_metadata_url="https://conformance-test.local/client-metadata.json",
    )

    await _run_auth_session(server_url, oauth_auth)


@register("auth/cross-app-access-complete-flow")
async def run_cross_app_access_complete_flow(server_url: str) -> None:
    """Enterprise managed auth: Complete SEP-990 flow (OIDC ID token → ID-JAG → access token).

    This scenario is provided by @modelcontextprotocol/conformance@0.1.14+ (PR #110).
    It tests the complete enterprise managed OAuth flow using token exchange (RFC 8693)
    and JWT bearer grant (RFC 7523).
    """
    from mcp.client.auth.extensions.enterprise_managed_auth import (
        EnterpriseAuthOAuthClientProvider,
        TokenExchangeParameters,
    )

    context = get_conformance_context()
    # The conformance package provides these fields
    idp_id_token = context.get("idp_id_token")
    idp_token_endpoint = context.get("idp_token_endpoint")
    idp_issuer = context.get("idp_issuer")

    # For cross-app access, we need to determine the MCP server's resource ID and auth issuer
    # The conformance package sets up the auth server, and the MCP server URL is passed to us

    if not idp_id_token:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'idp_id_token'")
    if not idp_token_endpoint:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'idp_token_endpoint'")
    if not idp_issuer:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'idp_issuer'")

    # Extract base URL and construct auth issuer and resource ID
    # The conformance test sets up auth server at a known location
    base_url = server_url.replace("/mcp", "")
    auth_issuer = context.get("auth_issuer", base_url)
    resource_id = context.get("resource_id", server_url)

    logger.debug("Cross-app access flow:")
    logger.debug(f"  IDP Issuer: {idp_issuer}")
    logger.debug(f"  IDP Token Endpoint: {idp_token_endpoint}")
    logger.debug(f"  Auth Issuer: {auth_issuer}")
    logger.debug(f"  Resource ID: {resource_id}")

    # Create token exchange parameters from IDP ID token
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=idp_id_token,
        mcp_server_auth_issuer=auth_issuer,
        mcp_server_resource_id=resource_id,
        scope=context.get("scope"),
    )

    # Get pre-configured client credentials from context (if provided)
    client_id = context.get("client_id")
    client_secret = context.get("client_secret")

    # Create storage and pre-configure client info if credentials are provided
    storage = InMemoryTokenStorage()

    # Create enterprise auth provider
    enterprise_auth = EnterpriseAuthOAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="conformance-cross-app-client",
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
            grant_types=["urn:ietf:params:oauth:grant-type:jwt-bearer"],
            response_types=["token"],
        ),
        storage=storage,
        idp_token_endpoint=idp_token_endpoint,
        token_exchange_params=token_exchange_params,
    )

    # If client credentials are provided in context, use them instead of dynamic registration
    if client_id and client_secret:
        from mcp.shared.auth import OAuthClientInformationFull

        logger.debug(f"Using pre-configured client credentials: {client_id}")
        client_info = OAuthClientInformationFull(
            client_id=client_id,
            client_secret=client_secret,
            token_endpoint_auth_method="client_secret_basic",
            grant_types=["urn:ietf:params:oauth:grant-type:jwt-bearer"],
            response_types=["token"],
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
        )
        enterprise_auth.context.client_info = client_info
        await storage.set_client_info(client_info)

    await _run_auth_session(server_url, enterprise_auth)


@register("auth/enterprise-token-exchange")
async def run_enterprise_token_exchange(server_url: str) -> None:
    """Enterprise managed auth: Token exchange flow (RFC 8693) with OIDC ID token."""
    from mcp.client.auth.extensions.enterprise_managed_auth import (
        EnterpriseAuthOAuthClientProvider,
        TokenExchangeParameters,
    )

    context = get_conformance_context()
    id_token = context.get("id_token")
    idp_token_endpoint = context.get("idp_token_endpoint")
    mcp_server_auth_issuer = context.get("mcp_server_auth_issuer")
    mcp_server_resource_id = context.get("mcp_server_resource_id")
    scope = context.get("scope")

    if not id_token:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'id_token'")
    if not idp_token_endpoint:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'idp_token_endpoint'")
    if not mcp_server_auth_issuer:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'mcp_server_auth_issuer'")
    if not mcp_server_resource_id:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'mcp_server_resource_id'")

    # Create token exchange parameters
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=id_token,
        mcp_server_auth_issuer=mcp_server_auth_issuer,
        mcp_server_resource_id=mcp_server_resource_id,
        scope=scope,
    )

    # Create enterprise auth provider
    enterprise_auth = EnterpriseAuthOAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="conformance-enterprise-client",
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
            grant_types=["urn:ietf:params:oauth:grant-type:jwt-bearer"],
            response_types=["token"],
        ),
        storage=InMemoryTokenStorage(),
        idp_token_endpoint=idp_token_endpoint,
        token_exchange_params=token_exchange_params,
    )

    await _run_auth_session(server_url, enterprise_auth)


@register("auth/enterprise-saml-exchange")
async def run_enterprise_saml_exchange(server_url: str) -> None:
    """Enterprise managed auth: SAML assertion exchange flow (RFC 8693)."""
    from mcp.client.auth.extensions.enterprise_managed_auth import (
        EnterpriseAuthOAuthClientProvider,
        TokenExchangeParameters,
    )

    context = get_conformance_context()
    saml_assertion = context.get("saml_assertion")
    idp_token_endpoint = context.get("idp_token_endpoint")
    mcp_server_auth_issuer = context.get("mcp_server_auth_issuer")
    mcp_server_resource_id = context.get("mcp_server_resource_id")
    scope = context.get("scope")

    if not saml_assertion:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'saml_assertion'")
    if not idp_token_endpoint:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'idp_token_endpoint'")
    if not mcp_server_auth_issuer:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'mcp_server_auth_issuer'")
    if not mcp_server_resource_id:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'mcp_server_resource_id'")

    # Create token exchange parameters for SAML
    token_exchange_params = TokenExchangeParameters.from_saml_assertion(
        saml_assertion=saml_assertion,
        mcp_server_auth_issuer=mcp_server_auth_issuer,
        mcp_server_resource_id=mcp_server_resource_id,
        scope=scope,
    )

    # Create enterprise auth provider
    enterprise_auth = EnterpriseAuthOAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="conformance-enterprise-saml-client",
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
            grant_types=["urn:ietf:params:oauth:grant-type:jwt-bearer"],
            response_types=["token"],
        ),
        storage=InMemoryTokenStorage(),
        idp_token_endpoint=idp_token_endpoint,
        token_exchange_params=token_exchange_params,
    )

    await _run_auth_session(server_url, enterprise_auth)


@register("auth/enterprise-id-jag-validation")
async def run_id_jag_validation(server_url: str) -> None:
    """Validate ID-JAG token structure and claims (SEP-990)."""
    from mcp.client.auth.extensions.enterprise_managed_auth import (
        EnterpriseAuthOAuthClientProvider,
        TokenExchangeParameters,
        decode_id_jag,
        validate_token_exchange_params,
    )

    context = get_conformance_context()
    id_token = context.get("id_token")
    idp_token_endpoint = context.get("idp_token_endpoint")
    mcp_server_auth_issuer = context.get("mcp_server_auth_issuer")
    mcp_server_resource_id = context.get("mcp_server_resource_id")

    if not all([id_token, idp_token_endpoint, mcp_server_auth_issuer, mcp_server_resource_id]):
        raise RuntimeError("Missing required context parameters for ID-JAG validation")

    # Create and validate token exchange parameters
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=id_token,
        mcp_server_auth_issuer=mcp_server_auth_issuer,
        mcp_server_resource_id=mcp_server_resource_id,
    )

    logger.debug("Validating token exchange parameters")
    validate_token_exchange_params(token_exchange_params)
    logger.debug("Token exchange parameters validated successfully")

    # Create enterprise auth provider
    enterprise_auth = EnterpriseAuthOAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="conformance-validation-client",
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
            grant_types=["urn:ietf:params:oauth:grant-type:jwt-bearer"],
            response_types=["token"],
        ),
        storage=InMemoryTokenStorage(),
        idp_token_endpoint=idp_token_endpoint,
        token_exchange_params=token_exchange_params,
    )

    async with httpx.AsyncClient() as client:
        # Get ID-JAG
        id_jag = await enterprise_auth.exchange_token_for_id_jag(client)
        logger.debug(f"Obtained ID-JAG for validation: {id_jag[:50]}...")

        # Decode and validate ID-JAG claims
        logger.debug("Decoding ID-JAG token")
        claims = decode_id_jag(id_jag)

        # Validate required claims
        assert claims.typ == "oauth-id-jag+jwt", f"Invalid typ: {claims.typ}"
        assert claims.jti, "Missing jti claim"
        assert claims.iss, "Missing iss claim"
        assert claims.sub, "Missing sub claim"
        assert claims.aud, "Missing aud claim"
        assert claims.resource == mcp_server_resource_id, f"Invalid resource: {claims.resource}"
        assert claims.client_id, "Missing client_id claim"
        assert claims.exp > claims.iat, "Invalid expiration"

        logger.debug("ID-JAG validated successfully:")
        logger.debug(f"  Subject: {claims.sub}")
        logger.debug(f"  Issuer: {claims.iss}")
        logger.debug(f"  Audience: {claims.aud}")
        logger.debug(f"  Resource: {claims.resource}")
        logger.debug(f"  Client ID: {claims.client_id}")

    logger.debug("ID-JAG validation completed successfully")


async def _run_auth_session(server_url: str, oauth_auth: OAuthClientProvider) -> None:
    """Common session logic for all OAuth flows."""
    client = httpx.AsyncClient(auth=oauth_auth, timeout=30.0)
    async with streamable_http_client(url=server_url, http_client=client) as (read_stream, write_stream):
        async with ClientSession(
            read_stream, write_stream, elicitation_callback=default_elicitation_callback
        ) as session:
            await session.initialize()
            logger.debug("Initialized successfully")

            tools_result = await session.list_tools()
            logger.debug(f"Listed tools: {[t.name for t in tools_result.tools]}")

            # Call the first available tool (different tests have different tools)
            if tools_result.tools:
                tool_name = tools_result.tools[0].name
                try:
                    result = await session.call_tool(tool_name, {})
                    logger.debug(f"Called {tool_name}, result: {result}")
                except Exception as e:
                    logger.debug(f"Tool call result/error: {e}")

    logger.debug("Connection closed successfully")


def main() -> None:
    """Main entry point for the conformance client."""
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <server-url>", file=sys.stderr)
        sys.exit(1)

    server_url = sys.argv[1]
    scenario = os.environ.get("MCP_CONFORMANCE_SCENARIO")

    if scenario:
        logger.debug(f"Running explicit scenario '{scenario}' against {server_url}")
        handler = HANDLERS.get(scenario)
        if handler:
            asyncio.run(handler(server_url))
        elif scenario.startswith("auth/"):
            asyncio.run(run_auth_code_client(server_url))
        else:
            print(f"Unknown scenario: {scenario}", file=sys.stderr)
            sys.exit(1)
    else:
        logger.debug(f"Running default auth flow against {server_url}")
        asyncio.run(run_auth_code_client(server_url))


if __name__ == "__main__":
    main()
