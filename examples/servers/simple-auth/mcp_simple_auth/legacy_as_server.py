"""
Legacy Combined Authorization Server + Resource Server for MCP.

This server implements the old spec where MCP servers could act as both AS and RS.
Used for backwards compatibility testing with the new split AS/RS architecture.

NOTE: this is a simplified example for demonstration purposes.
This is not a production-ready implementation.


Usage:
    python -m mcp_simple_auth.legacy_as_server --port=8002
"""

import logging
from typing import Any, Literal

import click
from pydantic import AnyHttpUrl, BaseModel
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp.server import FastMCP

from .github_oauth_provider import GitHubOAuthProvider, GitHubOAuthSettings

logger = logging.getLogger(__name__)


class ServerSettings(BaseModel):
    """Settings for the simple GitHub MCP server."""

    # Server settings
    host: str = "localhost"
    port: int = 8000
    server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")
    github_callback_path: str = "http://localhost:8000/github/callback"


class SimpleGitHubOAuthProvider(GitHubOAuthProvider):
    """GitHub OAuth provider for legacy MCP server."""

    def __init__(self, github_settings: GitHubOAuthSettings, github_callback_path: str):
        super().__init__(github_settings, github_callback_path)


def create_simple_mcp_server(server_settings: ServerSettings, github_settings: GitHubOAuthSettings) -> FastMCP:
    """Create a simple FastMCP server with GitHub OAuth."""
    oauth_provider = SimpleGitHubOAuthProvider(github_settings, server_settings.github_callback_path)

    auth_settings = AuthSettings(
        issuer_url=server_settings.server_url,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[github_settings.mcp_scope],
            default_scopes=[github_settings.mcp_scope],
        ),
        required_scopes=[github_settings.mcp_scope],
        # No resource_server_url parameter in legacy mode
        resource_server_url=None,
    )

    app = FastMCP(
        name="Simple GitHub MCP Server",
        instructions="A simple MCP server with GitHub OAuth authentication",
        auth_server_provider=oauth_provider,
        host=server_settings.host,
        port=server_settings.port,
        debug=True,
        auth=auth_settings,
    )

    @app.custom_route("/github/callback", methods=["GET"])
    async def github_callback_handler(request: Request) -> Response:
        """Handle GitHub OAuth callback."""
        code = request.query_params.get("code")
        state = request.query_params.get("state")

        if not code or not state:
            raise HTTPException(400, "Missing code or state parameter")

        redirect_uri = await oauth_provider.handle_github_callback(code, state)
        return RedirectResponse(status_code=302, url=redirect_uri)

    def get_github_token() -> str:
        """Get the GitHub token for the authenticated user."""
        access_token = get_access_token()
        if not access_token:
            raise ValueError("Not authenticated")

        # Get GitHub token from mapping
        github_token = oauth_provider.token_mapping.get(access_token.token)

        if not github_token:
            raise ValueError("No GitHub token found for user")

        return github_token

    @app.tool()
    async def get_user_profile() -> dict[str, Any]:
        """Get the authenticated user's GitHub profile information.

        This is the only tool in our simple example. It requires the 'user' scope.
        """
        access_token = get_access_token()
        if not access_token:
            raise ValueError("Not authenticated")

        return await oauth_provider.get_github_user_info(access_token.token)

    return app


@click.command()
@click.option("--port", default=8000, help="Port to listen on")
@click.option(
    "--transport",
    default="streamable-http",
    type=click.Choice(["sse", "streamable-http"]),
    help="Transport protocol to use ('sse' or 'streamable-http')",
)
def main(port: int, transport: Literal["sse", "streamable-http"]) -> int:
    """Run the simple GitHub MCP server."""
    logging.basicConfig(level=logging.INFO)

    # Load GitHub settings from environment variables
    github_settings = GitHubOAuthSettings()

    # Validate required fields
    if not github_settings.github_client_id or not github_settings.github_client_secret:
        raise ValueError("GitHub credentials not provided")
    # Create server settings
    host = "localhost"
    server_url = f"http://{host}:{port}"
    server_settings = ServerSettings(
        host=host,
        port=port,
        server_url=AnyHttpUrl(server_url),
        github_callback_path=f"{server_url}/github/callback",
    )

    mcp_server = create_simple_mcp_server(server_settings, github_settings)
    logger.info(f"Starting server with {transport} transport")
    mcp_server.run(transport=transport)
    return 0


if __name__ == "__main__":
    main()  # type: ignore[call-arg]
