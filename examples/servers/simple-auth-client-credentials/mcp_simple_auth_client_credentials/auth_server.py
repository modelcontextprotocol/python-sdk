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

import click
from pydantic import AnyHttpUrl, BaseModel
from starlette.applications import Starlette
from starlette.endpoints import HTTPEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from uvicorn import Config, Server

from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.routes import cors_middleware, create_auth_routes
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.auth import OAuthMetadata

logger = logging.getLogger(__name__)

API_BASE = "https://discord.com"
API_ENDPOINT = f"{API_BASE}/api/v10"


class AuthServerSettings(BaseModel):
    """Settings for the Authorization Server."""

    # Server settings
    host: str = "localhost"
    port: int = 9000
    server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:9000")

def create_authorization_server(server_settings: AuthServerSettings) -> Starlette:
    """Create the Authorization Server application."""

    routes = [
        # Create RFC 8414 authorization server metadata endpoint
        Route(
            "/.well-known/oauth-authorization-server",
            endpoint=cors_middleware(
                MetadataHandler(metadata=OAuthMetadata(
                    issuer=server_settings.server_url,
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
    ]

    return Starlette(routes=routes)


async def run_server(server_settings: AuthServerSettings):
    """Run the Authorization Server."""
    auth_server = create_authorization_server(server_settings)

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
    logger.info(f"  - OAuth Metadata: {server_settings.server_url}/.well-known/oauth-authorization-server")
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

    asyncio.run(run_server(server_settings))
    return 0


if __name__ == "__main__":
    main()  # type: ignore[call-arg]
