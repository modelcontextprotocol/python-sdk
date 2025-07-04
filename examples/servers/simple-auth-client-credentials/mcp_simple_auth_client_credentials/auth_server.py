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
import secrets
from base64 import b64decode, b64encode
from typing import Literal

import click
from pydantic import AnyHttpUrl, BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.applications import Starlette
from starlette.endpoints import HTTPEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import Receive, Scope, Send
from uvicorn import Config, Server

from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.routes import cors_middleware
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.auth import OAuthMetadata, OAuthToken

logger = logging.getLogger(__name__)

API_ENDPOINT = "https://discord.com/api/v10"


class DiscordOAuthSettings(BaseSettings):
    """Discord OAuth settings."""

    model_config = SettingsConfigDict(env_prefix="MCP_")

    # Discord OAuth settings - MUST be provided via environment variables
    discord_client_id: str | None = None
    discord_client_secret: str | None = None

    token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post"] = "client_secret_basic"

    # Discord OAuth URL
    discord_token_url: str = f"{API_ENDPOINT}/oauth2/token"

    discord_scope: str = "identify"


class AuthServerSettings(BaseModel):
    """Settings for the Authorization Server."""

    # Server settings
    host: str = "localhost"
    port: int = 9000
    server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:9000")


# Hardcoded credentials assuming a preconfigured client, to demonstrate
# working with an AS that does not have DCR support
MCP_CLIENT_ID = "0000000000000000000"
MCP_CLIENT_SECRET = "aaaaaaaaaaaaaaaaaaa"

# Map of MCP server tokens to Discord API tokens
TOKEN_MAP: dict[str, str] = {}


class TokenEndpoint(HTTPEndpoint):
    # Map of MCP client IDs to Discord client IDs
    client_map: dict[str, str] = {}
    client_credentials: dict[str, str] = {}

    discord_client_credentials: dict[str, str] = {}

    def __init__(self, scope: Scope, receive: Receive, send: Send):
        super().__init__(scope, receive, send)
        self.discord_settings = DiscordOAuthSettings()

        assert self.discord_settings.discord_client_id is not None, "Discord client ID not set"
        assert self.discord_settings.discord_client_secret is not None, "Discord client secret not set"

        # Assume a preconfigured client ID to demonstrate working with an AS that does not have DCR support
        self.client_map = {
            MCP_CLIENT_ID: self.discord_settings.discord_client_id,
        }
        self.client_credentials = {
            MCP_CLIENT_ID: MCP_CLIENT_SECRET,
        }
        self.discord_client_credentials = {
            self.discord_settings.discord_client_id: self.discord_settings.discord_client_secret,
        }

    async def post(self, request: Request) -> Response:
        # Get request data (application/x-www-form-urlencoded)
        data = await request.form()

        if self.discord_settings.token_endpoint_auth_method == "client_secret_basic":
            # Get client_id and client_secret from Basic auth header
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Basic "):
                return JSONResponse({"error": "Invalid authorization header"}, status_code=401)
            auth_header_encoded = auth_header.split(" ")[1]
            auth_header_raw = b64decode(auth_header_encoded).decode("utf-8")
            client_id, client_secret = auth_header_raw.split(":")
        else:
            # Get from body
            client_id = str(data.get("client_id"))
            client_secret = str(data.get("client_secret"))

        # Validate MCP client
        if client_id not in self.client_map:
            return JSONResponse({"error": "Invalid client"}, status_code=401)
        # Check if client secret matches
        if client_secret != self.client_credentials[client_id]:
            return JSONResponse({"error": "Invalid client secret"}, status_code=401)

        # Get mapped credentials
        discord_client_id = self.client_map[client_id]
        discord_client_secret = self.discord_client_credentials[discord_client_id]

        # Validate scopes
        scopes = str(data.get("scope", "")).split(" ")
        if not set(scopes).issubset(set(self.discord_settings.discord_scope.split(" "))):
            return JSONResponse({"error": "Invalid scope"}, status_code=400)

        # Set credentials in HTTP client
        headers = {
            "Authorization": f"Basic {b64encode(f'{discord_client_id}:{discord_client_secret}'.encode()).decode()}"
        }

        # Create HTTP client
        async with create_mcp_http_client() as http_client:
            # Forward request to Discord API
            method = getattr(http_client, request.method.lower())
            response = await method(self.discord_settings.discord_token_url, data=data, headers=headers)
            if response.status_code != 200:
                body = await response.aread()
                return Response(body, status_code=response.status_code, headers=response.headers)

            # Generate MCP access token
            mcp_token = f"mcp_{secrets.token_hex(32)}"

            # Store mapped access token
            TOKEN_MAP[mcp_token] = response.json()["access_token"]

            # Return response
            return JSONResponse(
                OAuthToken(
                    access_token=mcp_token,
                    token_type="Bearer",
                    expires_in=response.json()["expires_in"],
                    scope=self.discord_settings.discord_scope,
                ).model_dump(),
                status_code=response.status_code,
            )


class DiscordAPIProxy(HTTPEndpoint):
    """Proxy for Discord API."""

    async def get(self, request: Request) -> Response:
        """Proxy GET requests to Discord API."""
        return await self.handle(request)

    async def post(self, request: Request) -> Response:
        """Proxy POST requests to Discord API."""
        return await self.handle(request)

    async def handle(self, request: Request) -> Response:
        """Proxy requests to Discord API."""
        path = request.url.path[len("/discord") :]
        query = request.url.query

        # Get access token from Authorization header
        access_token = request.headers.get("Authorization", "").split(" ")[1]
        if not access_token:
            return JSONResponse({"error": "Missing access token"}, status_code=401)

        # Map access token to Discord access token
        access_token = TOKEN_MAP.get(access_token, None)
        if not access_token:
            return JSONResponse({"error": "Invalid access token"}, status_code=401)

        # Set mapped access token in HTTP client
        headers = {"Authorization": f"Bearer {access_token}"}

        # Create HTTP client
        async with create_mcp_http_client() as http_client:
            # Forward request to Discord API
            response = await http_client.get(f"{API_ENDPOINT}{path}?{query}", headers=headers)

            # Return response
            return JSONResponse(response.json(), status_code=response.status_code)


def create_authorization_server(
    server_settings: AuthServerSettings, discord_settings: DiscordOAuthSettings
) -> Starlette:
    """Create the Authorization Server application."""

    routes = [
        # Create RFC 8414 authorization server metadata endpoint
        Route(
            "/.well-known/oauth-authorization-server",
            endpoint=cors_middleware(
                MetadataHandler(
                    metadata=OAuthMetadata(
                        issuer=server_settings.server_url,
                        authorization_endpoint=AnyHttpUrl(f"{server_settings.server_url}authorize"),
                        token_endpoint=AnyHttpUrl(f"{server_settings.server_url}token"),
                        token_endpoint_auth_methods_supported=["client_secret_post"],
                        response_types_supported=["code"],
                        grant_types_supported=["client_credentials"],
                        scopes_supported=[discord_settings.discord_scope],
                    )
                ).handle,
                ["GET", "OPTIONS"],
            ),
            methods=["GET", "OPTIONS"],
        ),
        # Create OAuth 2.0 token endpoint
        Route("/token", TokenEndpoint),
        # Create API proxy endpoint
        Route("/discord/{path:path}", DiscordAPIProxy),
    ]

    return Starlette(routes=routes)


async def run_server(server_settings: AuthServerSettings, discord_settings: DiscordOAuthSettings):
    """Run the Authorization Server."""
    auth_server = create_authorization_server(server_settings, discord_settings)

    config = Config(
        auth_server,
        host=server_settings.host,
        port=server_settings.port,
        log_level="info",
    )
    server = Server(config)

    logger.info("=" * 80)
    logger.info("MCP AUTHORIZATION PROXY SERVER")
    logger.info("=" * 80)
    logger.info(f"Server URL: {server_settings.server_url}")
    logger.info("Endpoints:")
    logger.info(f"  - OAuth Metadata: {server_settings.server_url}.well-known/oauth-authorization-server")
    logger.info(f"  - Token Exchange: {server_settings.server_url}token")
    logger.info(f"  - Discord API Proxy: {server_settings.server_url}discord")
    logger.info("")
    logger.info("=" * 80)

    await server.serve()


@click.command()
@click.option("--port", default=9000, help="Port to listen on")
def main(port: int) -> int:
    """
    Run the MCP Authorization Server.

    This server handles OAuth flows and can be used by multiple Resource Servers.
    """
    logging.basicConfig(level=logging.INFO)

    # Create server settings
    host = "localhost"
    server_url = f"http://{host}:{port}"
    server_settings = AuthServerSettings(
        host=host,
        port=port,
        server_url=AnyHttpUrl(server_url),
    )

    discord_settings = DiscordOAuthSettings()

    asyncio.run(run_server(server_settings, discord_settings))
    return 0


if __name__ == "__main__":
    main()  # type: ignore[call-arg]
