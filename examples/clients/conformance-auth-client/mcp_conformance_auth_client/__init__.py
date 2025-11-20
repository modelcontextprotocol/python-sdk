#!/usr/bin/env python3
"""
MCP OAuth conformance test client.

This client is designed to work with the MCP conformance test framework.
It automatically handles OAuth flows without user interaction by programmatically
fetching the authorization URL and extracting the auth code from the redirect.

Usage:
    python -m mcp_conformance_auth_client <server-url>
"""

import asyncio
import logging
import sys
from datetime import timedelta
from urllib.parse import ParseResult, parse_qs, urlparse

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import AnyUrl

# Set up logging to stderr (stdout is for conformance test output)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


class InMemoryTokenStorage(TokenStorage):
    """Simple in-memory token storage for conformance testing."""

    def __init__(self):
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
    """
    OAuth callback handler that automatically fetches the authorization URL
    and extracts the auth code, without requiring user interaction.

    This mimics the behavior of the TypeScript ConformanceOAuthProvider.
    """

    def __init__(self):
        self._auth_code: str | None = None
        self._state: str | None = None

    async def handle_redirect(self, authorization_url: str) -> None:
        """
        Fetch the authorization URL and extract the auth code from the redirect.

        The conformance test server returns a redirect with the auth code,
        so we can capture it programmatically.
        """
        logger.debug(f"Fetching authorization URL: {authorization_url}")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                authorization_url,
                follow_redirects=False,  # Don't follow redirects automatically
            )

            # Check for redirect response
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if location:
                    redirect_url: ParseResult = urlparse(location)
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
        """Return the captured auth code and state, then clear them for potential reuse."""
        if self._auth_code is None:
            raise RuntimeError("No authorization code available - was handle_redirect called?")
        auth_code = self._auth_code
        state = self._state
        # Clear the stored values so the next auth flow gets fresh ones
        self._auth_code = None
        self._state = None
        return auth_code, state


async def run_client(server_url: str) -> None:
    """
    Run the conformance test client against the given server URL.

    This function:
    1. Connects to the MCP server with OAuth authentication
    2. Initializes the session
    3. Lists available tools
    4. Calls a test tool
    """
    logger.debug(f"Starting conformance auth client for {server_url}")

    # Create callback handler that will automatically fetch auth codes
    callback_handler = ConformanceOAuthCallbackHandler()

    # Create OAuth authentication handler
    oauth_auth = OAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="conformance-auth-client",
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=InMemoryTokenStorage(),
        redirect_handler=callback_handler.handle_redirect,
        callback_handler=callback_handler.handle_callback,
    )

    # Connect using streamable HTTP transport with OAuth
    async with streamablehttp_client(
        url=server_url,
        auth=oauth_auth,
        timeout=timedelta(seconds=30),
        sse_read_timeout=timedelta(seconds=60),
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize the session
            await session.initialize()
            logger.debug("Successfully connected and initialized MCP session")

            # List tools
            tools_result = await session.list_tools()
            logger.debug(f"Listed tools: {[t.name for t in tools_result.tools]}")

            # Call test tool (expected by conformance tests)
            try:
                result = await session.call_tool("test-tool", {})
                logger.debug(f"Called test-tool, result: {result}")
            except Exception as e:
                logger.debug(f"Tool call result/error: {e}")

    logger.debug("Connection closed successfully")


def main() -> None:
    """Main entry point for the conformance auth client."""
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <server-url>", file=sys.stderr)
        sys.exit(1)

    server_url = sys.argv[1]

    try:
        asyncio.run(run_client(server_url))
    except Exception:
        logger.exception("Client failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
