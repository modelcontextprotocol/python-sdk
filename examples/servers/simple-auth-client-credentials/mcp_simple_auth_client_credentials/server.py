"""
MCP Resource Server.

Usage:
    python -m mcp_simple_auth.server --port=8001
"""

import asyncio
import logging
from typing import Any, Literal

import click
import httpx
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from uvicorn import Config, Server

from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.routes import cors_middleware
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp.server import FastMCP
from mcp.shared.auth import OAuthMetadata

from .token_verifier import IntrospectionTokenVerifier


logger = logging.getLogger(__name__)

API_ENDPOINT = "https://discord.com/api/v10"

class ResourceServerSettings(BaseSettings):
    """Settings for the MCP Resource Server."""

    model_config = SettingsConfigDict(env_prefix="MCP_RESOURCE_")

    # Server settings
    host: str = "localhost"
    port: int = 8001
    server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8001")
    transport: Literal["sse", "streamable-http"] = "streamable-http"

    # Authorization Server settings
    auth_server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8001")
    auth_server_introspection_endpoint: str = f"{API_ENDPOINT}/oauth2/@me"
    auth_server_discord_user_endpoint: str = f"{API_ENDPOINT}/users/@me"

    # MCP settings
    mcp_scope: str = "identify"

    def __init__(self, **data):
        """Initialize settings with values from environment variables."""
        super().__init__(**data)


def create_resource_server(settings: ResourceServerSettings) -> Starlette:
    """
    Create MCP Resource Server.
    """

    # Create token verifier for introspection with RFC 8707 resource validation
    token_verifier = IntrospectionTokenVerifier(
        introspection_endpoint=settings.auth_server_introspection_endpoint,
        server_url=str(settings.server_url),
    )

    # Create FastMCP server as a Resource Server
    resource_server = FastMCP(
        name="MCP Resource Server",
        debug=True,
        token_verifier=token_verifier,
        auth=AuthSettings(
            issuer_url=settings.auth_server_url,
            required_scopes=[settings.mcp_scope],
            resource_server_url=settings.server_url,
        ),
    )

    async def get_discord_user_data() -> dict[str, Any]:
        """
        Get Discord user data via the Discord API.
        """
        access_token = get_access_token()
        if not access_token:
            raise ValueError("Not authenticated")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                settings.auth_server_discord_user_endpoint,
                headers={
                    "Authorization": f"Bearer {access_token.token}",
                },
            )

            if response.status_code != 200:
                raise ValueError(f"Discord user data fetch failed: {response.status_code} - {response.text}")

            return response.json()

    @resource_server.tool()
    async def get_user_profile() -> dict[str, Any]:
        """
        Get the authenticated user's Discord profile information.
        """
        return await get_discord_user_data()

    @resource_server.tool()
    async def get_user_info() -> dict[str, Any]:
        """
        Get information about the currently authenticated user.

        Returns token and scope information from the Resource Server's perspective.
        """
        access_token = get_access_token()
        if not access_token:
            raise ValueError("Not authenticated")

        return {
            "authenticated": True,
            "client_id": access_token.client_id,
            "scopes": access_token.scopes,
            "token_expires_at": access_token.expires_at,
            "token_type": "Bearer",
            "resource_server": str(settings.server_url),
            "authorization_server": str(settings.auth_server_url),
        }

    # Create Starlette app to mount the MCP server and host RFC8414
    # metadata to jump to Discord's authorization server
    app = Starlette(
        debug=True,
        routes=[
            Route(
                "/.well-known/oauth-authorization-server",
                endpoint=cors_middleware(
                    MetadataHandler(metadata=OAuthMetadata(
                        issuer=settings.server_url,
                        authorization_endpoint=AnyHttpUrl(f"{API_ENDPOINT}/oauth2/authorize"),
                        token_endpoint=AnyHttpUrl(f"{API_ENDPOINT}/oauth2/token"),
                        token_endpoint_auth_methods_supported=["client_secret_basic"],
                        response_types_supported=["code"],
                        grant_types_supported=["client_credentials"],
                        scopes_supported=["identify"]
                    )).handle,
                    ["GET", "OPTIONS"],
                ),
                methods=["GET", "OPTIONS"],
            ),
            Mount(
                "/",
                app=resource_server.streamable_http_app() if settings.transport == "streamable-http" else resource_server.sse_app()
            ),
        ],
        lifespan=lambda app: resource_server.session_manager.run(),
    )

    return app


async def run_server(settings: ResourceServerSettings):
    mcp_server = create_resource_server(settings)
    config = Config(
        mcp_server,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
    server = Server(config)
    await server.serve()


@click.command()
@click.option("--port", default=8001, help="Port to listen on")
@click.option("--auth-server", default="http://localhost:8001", help="Authorization Server URL")
@click.option(
    "--transport",
    default="streamable-http",
    type=click.Choice(["sse", "streamable-http"]),
    help="Transport protocol to use ('sse' or 'streamable-http')",
)
def main(port: int, auth_server: str, transport: Literal["sse", "streamable-http"]) -> int:
    """
    Run the MCP Resource Server.
    """
    logging.basicConfig(level=logging.INFO)

    try:
        # Parse auth server URL
        auth_server_url = AnyHttpUrl(auth_server)

        # Create settings
        host = "localhost"
        server_url = f"http://{host}:{port}"
        settings = ResourceServerSettings(
            host=host,
            port=port,
            server_url=AnyHttpUrl(server_url),
            auth_server_url=auth_server_url,
            auth_server_introspection_endpoint=f"{API_ENDPOINT}/oauth2/@me",
            auth_server_discord_user_endpoint=f"{API_ENDPOINT}/users/@me",
            transport=transport,
        )
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Make sure to provide a valid Authorization Server URL")
        return 1

    try:
        logger.info("=" * 80)
        logger.info("📦 MCP RESOURCE SERVER")
        logger.info("=" * 80)
        logger.info(f"🌐 Server URL: {settings.server_url}")
        logger.info(f"🔑 Authorization Server: {settings.auth_server_url}")
        logger.info("📋 Endpoints:")
        logger.info(f"   ┌─ Protected Resource Metadata: {settings.server_url}/.well-known/oauth-protected-resource")
        mcp_path = "sse" if transport == "sse" else "mcp"
        logger.info(f"   ├─ MCP Protocol: {settings.server_url}/{mcp_path}")
        logger.info(f"   └─ Token Introspection: {settings.auth_server_introspection_endpoint}")
        logger.info("")
        logger.info("🛠️  Available Tools:")
        logger.info("   ├─ get_user_profile() - Get Discord user profile")
        logger.info("   └─ get_user_info() - Get authentication status")
        logger.info("")
        logger.info("🔍 Tokens validated via Authorization Server introspection")
        logger.info("📱 Clients discover Authorization Server via Protected Resource Metadata")
        logger.info("=" * 80)

        # Run the server - this should block and keep running
        asyncio.run(run_server(settings))
        logger.info("Server stopped")
        return 0
    except Exception as e:
        logger.error(f"Server error: {e}")
        logger.exception("Exception details:")
        return 1


if __name__ == "__main__":
    main()  # type: ignore[call-arg]
