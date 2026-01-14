#!/usr/bin/env python3
"""
MCP Auth Test Server - Conformance Test Server with Authentication

A minimal MCP server that requires Bearer token authentication.
This server is used for testing OAuth authentication flows in conformance tests.

Required environment variables:
- MCP_CONFORMANCE_AUTH_SERVER_URL: URL of the authorization server

Optional environment variables:
- PORT: Server port (default: 3001)
"""

import logging
import os
import sys

import click
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl

logger = logging.getLogger(__name__)


class ConformanceTokenVerifier(TokenVerifier):
    """
    Token verifier for conformance testing.

    Validates Bearer tokens that start with 'test-token' or 'cc-token'
    (as issued by the fake auth server).
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a bearer token and return access info if valid."""
        # Accept tokens that start with 'test-token' or 'cc-token'
        if token.startswith("test-token") or token.startswith("cc-token"):
            return AccessToken(
                token=token,
                client_id="conformance-test-client",
                scopes=["mcp:read", "mcp:write"],
            )
        return None


def create_server(auth_server_url: str, port: int) -> FastMCP:
    """Create and configure the MCP auth test server."""
    base_url = f"http://localhost:{port}"

    mcp = FastMCP(
        name="mcp-auth-test-server",
        token_verifier=ConformanceTokenVerifier(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(auth_server_url),
            resource_server_url=AnyHttpUrl(base_url),
            required_scopes=[],  # No specific scopes required for conformance tests
        ),
        json_response=True,
        port=port,
    )

    @mcp.tool()
    def echo(message: str = "No message provided") -> str:
        """Echoes back the provided message - used for testing authenticated calls."""
        return f"Echo: {message}"

    @mcp.tool(name="test-tool")
    def test_tool() -> str:
        """A simple test tool that returns a success message."""
        return "test"

    return mcp


@click.command()
@click.option("--port", default=None, type=int, help="Port to listen on for HTTP")
@click.option(
    "--log-level",
    default="INFO",
    help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
)
def main(port: int | None, log_level: str) -> int:
    """Run the MCP Auth Test Server."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Check for required environment variable
    auth_server_url = os.environ.get("MCP_CONFORMANCE_AUTH_SERVER_URL")
    if not auth_server_url:
        logger.error("Error: MCP_CONFORMANCE_AUTH_SERVER_URL environment variable is required")
        logger.error(
            "Usage: MCP_CONFORMANCE_AUTH_SERVER_URL=http://localhost:3000 python -m mcp_conformance_auth_server"
        )
        sys.exit(1)

    # Get port from argument or environment
    if port is None:
        port = int(os.environ.get("PORT", "3001"))

    logger.info(f"Starting MCP Auth Test Server on port {port}")
    logger.info(f"Endpoint will be: http://localhost:{port}/mcp")
    logger.info(f"PRM endpoint: http://localhost:{port}/.well-known/oauth-protected-resource")
    logger.info(f"Auth server: {auth_server_url}")

    mcp = create_server(auth_server_url, port)
    mcp.run(transport="streamable-http")

    return 0


if __name__ == "__main__":
    main()
