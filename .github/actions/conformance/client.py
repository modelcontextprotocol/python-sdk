"""MCP unified conformance test client.

This client is designed to work with the @modelcontextprotocol/conformance npm package.
It handles all conformance test scenarios via environment variables and CLI arguments.

Contract:
    - MCP_CONFORMANCE_SCENARIO env var -> scenario name
    - MCP_CONFORMANCE_CONTEXT env var -> optional JSON (for client-credentials scenarios)
    - Server URL as last CLI argument (sys.argv[1])
    - Must exit 0 within 30 seconds

Scenarios:
    initialize                              - Connect, initialize, list tools, close
    tools_call                              - Connect, call add_numbers(a=5, b=3), close
    sse-retry                               - Connect, call test_reconnection, close
    elicitation-sep1034-client-defaults     - Elicitation with default accept callback
    auth/client-credentials-jwt             - Client credentials with private_key_jwt
    auth/client-credentials-basic           - Client credentials with client_secret_basic
    auth/*                                  - Authorization code flow (default for auth scenarios)
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
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from mcp.shared.context import RequestContext

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
    async with streamable_http_client(url=server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            logger.debug("Initialized successfully")
            await session.list_tools()
            logger.debug("Listed tools successfully")


@register("tools_call")
async def run_tools_call(server_url: str) -> None:
    """Connect, initialize, list tools, call add_numbers(a=5, b=3), close."""
    async with streamable_http_client(url=server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            await session.list_tools()
            result = await session.call_tool("add_numbers", {"a": 5, "b": 3})
            logger.debug(f"add_numbers result: {result}")


@register("sse-retry")
async def run_sse_retry(server_url: str) -> None:
    """Connect, initialize, list tools, call test_reconnection, close."""
    async with streamable_http_client(url=server_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            await session.list_tools()
            result = await session.call_tool("test_reconnection", {})
            logger.debug(f"test_reconnection result: {result}")


async def default_elicitation_callback(
    context: RequestContext[ClientSession, Any],  # noqa: ARG001
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
    async with streamable_http_client(url=server_url) as (read_stream, write_stream, _):
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

    oauth_auth = OAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="conformance-client",
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=InMemoryTokenStorage(),
        redirect_handler=callback_handler.handle_redirect,
        callback_handler=callback_handler.handle_callback,
        client_metadata_url="https://conformance-test.local/client-metadata.json",
    )

    await _run_auth_session(server_url, oauth_auth)


async def _run_auth_session(server_url: str, oauth_auth: OAuthClientProvider) -> None:
    """Common session logic for all OAuth flows."""
    client = httpx.AsyncClient(auth=oauth_auth, timeout=30.0)
    async with streamable_http_client(url=server_url, http_client=client) as (read_stream, write_stream, _):
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
