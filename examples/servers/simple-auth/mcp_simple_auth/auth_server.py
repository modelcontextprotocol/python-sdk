"""
Authorization Server for MCP Split Demo.

This server handles OAuth flows, client registration, and token issuance.
Can be replaced with enterprise authorization servers like Auth0, Entra ID, etc.

NOTE: this is a simplified example for demonstration purposes.
This is not a production-ready implementation.

Usage:
    python -m mcp_simple_auth.auth_server --port=9000
"""

import asyncio
import logging
import time

import click
from pydantic import AnyHttpUrl, BaseModel
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route
from uvicorn import Config, Server

from mcp.server.auth.routes import cors_middleware, create_auth_routes
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions

from .github_oauth_provider import GitHubOAuthProvider, GitHubOAuthSettings

logger = logging.getLogger(__name__)


class AuthServerSettings(BaseModel):
    """Settings for the Authorization Server."""

    # Server settings
    host: str = "localhost"
    port: int = 9000
    server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:9000")
    github_callback_path: str = "http://localhost:9000/github/callback"


class GitHubProxyAuthProvider(GitHubOAuthProvider):
    """
    Authorization Server provider that proxies GitHub OAuth.

    This provider:
    1. Issues MCP tokens after GitHub authentication
    2. Stores token state for introspection by Resource Servers
    3. Maps MCP tokens to GitHub tokens for API access
    """

    def __init__(self, github_settings: GitHubOAuthSettings, github_callback_path: str):
        super().__init__(github_settings, github_callback_path)


def create_authorization_server(server_settings: AuthServerSettings, github_settings: GitHubOAuthSettings) -> Starlette:
    """Create the Authorization Server application."""
    oauth_provider = GitHubProxyAuthProvider(github_settings, server_settings.github_callback_path)

    auth_settings = AuthSettings(
        issuer_url=server_settings.server_url,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[github_settings.mcp_scope],
            default_scopes=[github_settings.mcp_scope],
        ),
        required_scopes=[github_settings.mcp_scope],
        resource_server_url=None,
    )

    # Create OAuth routes
    routes = create_auth_routes(
        provider=oauth_provider,
        issuer_url=auth_settings.issuer_url,
        service_documentation_url=auth_settings.service_documentation_url,
        client_registration_options=auth_settings.client_registration_options,
        revocation_options=auth_settings.revocation_options,
    )

    # Add GitHub callback route
    async def github_callback_handler(request: Request) -> Response:
        """Handle GitHub OAuth callback."""
        code = request.query_params.get("code")
        state = request.query_params.get("state")

        if not code or not state:
            raise HTTPException(400, "Missing code or state parameter")

        redirect_uri = await oauth_provider.handle_github_callback(code, state)
        return RedirectResponse(url=redirect_uri, status_code=302)

    routes.append(Route("/github/callback", endpoint=github_callback_handler, methods=["GET"]))

    # Add token introspection endpoint (RFC 7662) for Resource Servers
    async def introspect_handler(request: Request) -> Response:
        """
        Token introspection endpoint for Resource Servers.

        Resource Servers call this endpoint to validate tokens without
        needing direct access to token storage.
        """
        form = await request.form()
        token = form.get("token")
        if not token or not isinstance(token, str):
            return JSONResponse({"active": False}, status_code=400)

        # Look up token in provider
        access_token = await oauth_provider.load_access_token(token)
        if not access_token:
            return JSONResponse({"active": False})

        # Return token info for Resource Server
        return JSONResponse(
            {
                "active": True,
                "client_id": access_token.client_id,
                "scope": " ".join(access_token.scopes),
                "exp": access_token.expires_at,
                "iat": int(time.time()),
                "token_type": "Bearer",
                "aud": access_token.resource,  # RFC 8707 audience claim
            }
        )

    routes.append(
        Route(
            "/introspect",
            endpoint=cors_middleware(introspect_handler, ["POST", "OPTIONS"]),
            methods=["POST", "OPTIONS"],
        )
    )

    # Add GitHub user info endpoint (for Resource Server to fetch user data)
    async def github_user_handler(request: Request) -> Response:
        """
        Proxy endpoint to get GitHub user info using stored GitHub tokens.

        Resource Servers call this with MCP tokens to get GitHub user data
        without exposing GitHub tokens to clients.
        """
        # Extract Bearer token
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        mcp_token = auth_header[7:]

        # Get GitHub user info using the provider method
        user_info = await oauth_provider.get_github_user_info(mcp_token)
        return JSONResponse(user_info)

    routes.append(
        Route(
            "/github/user",
            endpoint=cors_middleware(github_user_handler, ["GET", "OPTIONS"]),
            methods=["GET", "OPTIONS"],
        )
    )

    return Starlette(routes=routes)


async def run_server(server_settings: AuthServerSettings, github_settings: GitHubOAuthSettings):
    """Run the Authorization Server."""
    auth_server = create_authorization_server(server_settings, github_settings)

    config = Config(
        auth_server,
        host=server_settings.host,
        port=server_settings.port,
        log_level="info",
    )
    server = Server(config)

    logger.info("=" * 80)
    logger.info("MCP AUTHORIZATION SERVER")
    logger.info("=" * 80)
    logger.info(f"Server URL: {server_settings.server_url}")
    logger.info("Endpoints:")
    logger.info(f"  - OAuth Metadata: {server_settings.server_url}/.well-known/oauth-authorization-server")
    logger.info(f"  - Client Registration: {server_settings.server_url}/register")
    logger.info(f"  - Authorization: {server_settings.server_url}/authorize")
    logger.info(f"  - Token Exchange: {server_settings.server_url}/token")
    logger.info(f"  - Token Introspection: {server_settings.server_url}/introspect")
    logger.info(f"  - GitHub Callback: {server_settings.server_url}/github/callback")
    logger.info(f"  - GitHub User Proxy: {server_settings.server_url}/github/user")
    logger.info("")
    logger.info("Resource Servers should use /introspect to validate tokens")
    logger.info("Configure GitHub App callback URL: " + server_settings.github_callback_path)
    logger.info("=" * 80)

    await server.serve()


@click.command()
@click.option("--port", default=9000, help="Port to listen on")
def main(port: int) -> int:
    """
    Run the MCP Authorization Server.

    This server handles OAuth flows and can be used by multiple Resource Servers.

    Environment variables needed:
    - MCP_GITHUB_CLIENT_ID: GitHub OAuth Client ID
    - MCP_GITHUB_CLIENT_SECRET: GitHub OAuth Client Secret
    """
    logging.basicConfig(level=logging.INFO)

    # Load GitHub settings from environment variables
    github_settings = GitHubOAuthSettings()

    # Validate required fields
    if not github_settings.github_client_id or not github_settings.github_client_secret:
        raise ValueError("GitHub credentials not provided")

    # Create server settings
    host = "localhost"
    server_url = f"http://{host}:{port}"
    server_settings = AuthServerSettings(
        host=host,
        port=port,
        server_url=AnyHttpUrl(server_url),
        github_callback_path=f"{server_url}/github/callback",
    )

    asyncio.run(run_server(server_settings, github_settings))
    return 0


if __name__ == "__main__":
    main()  # type: ignore[call-arg]
