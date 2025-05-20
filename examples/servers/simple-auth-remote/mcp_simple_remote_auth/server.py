"""Simple MCP Server with GitHub OAuth Authentication."""

import logging
from typing import Any, Literal

import click
import jwt
import requests
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp.server.auth.provider import (
    AccessToken,
    TokenValidator,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp.server import FastMCP
from mcp.shared.auth import ProtectedResourceMetadata

logger = logging.getLogger(__name__)


class TokenValidatorJWT(TokenValidator[AccessToken]):
    def __init__(self, resource_metadata: ProtectedResourceMetadata):
        self._resource_metadata = resource_metadata

    async def validate_token(self, token: str) -> AccessToken | None:
        try:
            return await self.decode_token(token)
        except Exception as e:
            logger.error(f"Token validation failed: {e}")
            return None

    async def _get_jwks_uri(self, auth_server: str) -> str:
        """Get the JWKS URI from the OIDC or OAuth well-known configuration.

        Args:
            auth_server: The base URL of the authorization server

        Returns:
            The JWKS URI

        Raises:
            ValueError: If the JWKS URI cannot be found in either OIDC or OAuth
            well-known configurations
            requests.RequestException: If there's an error fetching the configuration
        """
        well_known_paths = [
            "/.well-known/openid-configuration",  # OIDC well-known
            "/.well-known/oauth-authorization-server",  # OAuth well-known
        ]

        last_error = None

        for path in well_known_paths:
            try:
                config_url = f"https://{auth_server}{path}"
                response = requests.get(
                    config_url,
                    timeout=10,  # Add timeout to prevent hanging
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()  # Raise an exception for bad status codes
                config = response.json()

                # Try to get JWKS URI from the configuration
                jwks_uri = config.get("jwks_uri")
                if jwks_uri:
                    return jwks_uri

            except requests.RequestException as e:
                last_error = e
                logger.debug(f"Failed to fetch {path}: {e}")
                continue

        # If we get here, we couldn't find a valid JWKS URI
        error_msg = "Could not find jwks_uri in OIDC or OAuth well-known configurations"
        logger.error(f"{error_msg}. Last error: {last_error}")
        raise ValueError(error_msg)

    async def decode_token(self, token: str) -> AccessToken | None:
        try:
            auth_server = self._resource_metadata.authorization_servers[0]
            jwks_uri = await self._get_jwks_uri(auth_server)
            jwks_client = jwt.PyJWKClient(jwks_uri)
            signing_key = jwks_client.get_signing_key_from_jwt(token)

            # Rest of your decode_token method remains the same
            payload = jwt.decode(
                token,
                key=signing_key.key,
                algorithms=["RS256"],
                audience=self._resource_metadata.resource,
                issuer=f"https://{auth_server}",
                options={
                    "verify_signature": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                },
            )

            return AccessToken(
                token=token,
                client_id=payload["client_id"],
                scopes=payload["scope"].split(" "),
                expires_at=payload["exp"],
            )
        except Exception as e:
            logger.error(f"Token validation failed: {e}")
            return None


class ServerSettings(BaseSettings):
    """Settings for the simple GitHub MCP server."""

    model_config = SettingsConfigDict(env_prefix="MCP_GITHUB_")

    # Server settings
    host: str = "localhost"
    port: int = 8000
    server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")
    mcp_scope: str = "user"

    def __init__(self, **data):
        """Initialize settings with values from environment variables.

        Note: github_client_id and github_client_secret are required but can be
        loaded automatically from environment variables (MCP_GITHUB_GITHUB_CLIENT_ID
        and MCP_GITHUB_GITHUB_CLIENT_SECRET) and don't need to be passed explicitly.
        """
        super().__init__(**data)


def create_simple_mcp_server(settings: ServerSettings) -> FastMCP:
    """Create a simple FastMCP server with GitHub OAuth."""

    auth_settings = AuthSettings(
        issuer_url=settings.server_url,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[settings.mcp_scope],
            default_scopes=[settings.mcp_scope],
        ),
        required_scopes=[settings.mcp_scope],
    )

    app = FastMCP(
        name="Simple GitHub MCP Server",
        instructions="A simple MCP server with GitHub OAuth authentication",
        host=settings.host,
        port=settings.port,
        debug=True,
        auth=auth_settings,
        token_validator=TokenValidatorJWT(
            ProtectedResourceMetadata(
                resource="asdasd",
                authorization_servers=["https://auth.devramp.ai"],
                scopes_supported=["user"],
            )
        ),
        protected_resource_metadata={
            "resource": "asdasd",
            "authorization_servers": ["https://auth.devramp.ai"],
            "scopes_supported": ["user"],
        },
    )

    @app.tool()
    async def get_user_profile() -> dict[str, Any]:
        """Get the authenticated user's GitHub profile information.

        This is the only tool in our simple example. It requires the 'user' scope.
        """
        return {"user": "asdasd"}

    return app


@click.command()
@click.option("--port", default=8000, help="Port to listen on")
@click.option("--host", default="localhost", help="Host to bind to")
@click.option(
    "--transport",
    default="streamable-http",
    type=click.Choice(["sse", "streamable-http"]),
    help="Transport protocol to use ('sse' or 'streamable-http')",
)
def main(port: int, host: str, transport: Literal["sse", "streamable-http"]) -> int:
    """Run the simple GitHub MCP server."""
    logging.basicConfig(level=logging.INFO)

    try:
        # No hardcoded credentials - all from environment variables
        settings = ServerSettings(host=host, port=port)
    except ValueError as e:
        logger.error(
            "Failed to load settings. Make sure environment variables are set:"
        )
        logger.error("  MCP_GITHUB_GITHUB_CLIENT_ID=<your-client-id>")
        logger.error("  MCP_GITHUB_GITHUB_CLIENT_SECRET=<your-client-secret>")
        logger.error(f"Error: {e}")
        return 1

    mcp_server = create_simple_mcp_server(settings)
    logger.info(f"Starting server with {transport} transport")
    mcp_server.run(transport=transport)
    return 0
