"""MCP Resource Server that validates tokens via Authorization Server introspection.

Demonstrates RFC 9728 Protected Resource Metadata for AS/RS separation.
Simplified for demonstration; not production-ready.
"""

import datetime
import logging
from typing import Any, Literal

import click
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.server import MCPServer

from .token_verifier import IntrospectionTokenVerifier

logger = logging.getLogger(__name__)


class ResourceServerSettings(BaseSettings):
    """Settings for the MCP Resource Server."""

    model_config = SettingsConfigDict(env_prefix="MCP_RESOURCE_")

    host: str = "localhost"
    port: int = 8001
    server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8001/mcp")

    # No user endpoint needed - user data comes from token introspection
    auth_server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:9000")
    auth_server_introspection_endpoint: str = "http://localhost:9000/introspect"

    mcp_scope: str = "user"

    # RFC 8707 resource validation
    oauth_strict: bool = False


def create_resource_server(settings: ResourceServerSettings) -> MCPServer:
    """Create a Resource Server that serves RFC 9728 metadata and validates tokens via AS introspection."""
    token_verifier = IntrospectionTokenVerifier(
        introspection_endpoint=settings.auth_server_introspection_endpoint,
        server_url=str(settings.server_url),
        validate_resource=settings.oauth_strict,  # RFC 8707 validation, only when --oauth-strict is set
    )

    app = MCPServer(
        name="MCP Resource Server",
        instructions="Resource Server that validates tokens via Authorization Server introspection",
        debug=True,
        token_verifier=token_verifier,
        auth=AuthSettings(
            issuer_url=settings.auth_server_url,
            required_scopes=[settings.mcp_scope],
            resource_server_url=settings.server_url,
        ),
    )
    # Store settings for later use in run()
    app._resource_server_settings = settings  # type: ignore[attr-defined]

    @app.tool()
    async def get_time() -> dict[str, Any]:
        """Get the current server time (requires OAuth authentication)."""
        now = datetime.datetime.now()

        return {
            "current_time": now.isoformat(),
            "timezone": "UTC",  # Simplified for demo
            "timestamp": now.timestamp(),
            "formatted": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

    return app


@click.command()
@click.option("--port", default=8001, help="Port to listen on")
@click.option("--auth-server", default="http://localhost:9000", help="Authorization Server URL")
@click.option(
    "--transport",
    default="streamable-http",
    type=click.Choice(["sse", "streamable-http"]),
    help="Transport protocol to use ('sse' or 'streamable-http')",
)
@click.option(
    "--oauth-strict",
    is_flag=True,
    help="Enable RFC 8707 resource validation",
)
def main(port: int, auth_server: str, transport: Literal["sse", "streamable-http"], oauth_strict: bool) -> int:
    """Run the MCP Resource Server.

    Must be used with a running Authorization Server.
    """
    logging.basicConfig(level=logging.INFO)

    try:
        auth_server_url = AnyHttpUrl(auth_server)

        host = "localhost"
        server_url = f"http://{host}:{port}/mcp"
        settings = ResourceServerSettings(
            host=host,
            port=port,
            server_url=AnyHttpUrl(server_url),
            auth_server_url=auth_server_url,
            auth_server_introspection_endpoint=f"{auth_server}/introspect",
            oauth_strict=oauth_strict,
        )
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Make sure to provide a valid Authorization Server URL")
        return 1

    try:
        mcp_server = create_resource_server(settings)

        logger.info(f"🚀 MCP Resource Server running on {settings.server_url}")
        logger.info(f"🔑 Using Authorization Server: {settings.auth_server_url}")

        mcp_server.run(transport=transport, host=host, port=port)
        logger.info("Server stopped")
        return 0
    except Exception:
        logger.exception("Server error")
        return 1


if __name__ == "__main__":
    main()  # type: ignore[call-arg]
