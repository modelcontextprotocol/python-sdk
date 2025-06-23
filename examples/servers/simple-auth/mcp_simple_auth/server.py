"""
MCP Resource Server with Token Introspection.

This server validates tokens via Authorization Server introspection and serves MCP resources.
Demonstrates RFC 9728 Protected Resource Metadata for AS/RS separation.

Usage:
    python -m mcp_simple_auth.server --port=8001 --auth-server=http://localhost:9000
"""

import logging
from typing import Any, Literal

import click
import httpx
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp.server import FastMCP

from .token_verifier import IntrospectionTokenVerifier

logger = logging.getLogger(__name__)


class ResourceServerSettings(BaseSettings):
    """Settings for the MCP Resource Server."""

    model_config = SettingsConfigDict(env_prefix="MCP_RESOURCE_")

    # Server settings
    host: str = "localhost"
    port: int = 8001
    server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8001")

    # Authorization Server settings
    auth_server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:9000")
    auth_server_introspection_endpoint: str = "http://localhost:9000/introspect"
    auth_server_github_user_endpoint: str = "http://localhost:9000/github/user"

    # MCP settings
    mcp_scope: str = "user"

    # RFC 8707 resource validation
    oauth_strict: bool = False

    def __init__(self, **data):
        """Initialize settings with values from environment variables."""
        super().__init__(**data)


# <<<<<<< main
class SimpleGitHubOAuthProvider(OAuthAuthorizationServerProvider):
    """Simple GitHub OAuth provider with essential functionality."""

    def __init__(self, settings: ServerSettings):
        self.settings = settings
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.tokens: dict[str, AccessToken] = {}
        self.state_mapping: dict[str, dict[str, str]] = {}
        # Store GitHub tokens with MCP tokens using the format:
        # {"mcp_token": "github_token"}
        self.token_mapping: dict[str, str] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Get OAuth client information."""
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull):
        """Register a new OAuth client."""
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Generate an authorization URL for GitHub OAuth flow."""
        state = params.state or secrets.token_hex(16)

        # Store the state mapping
        self.state_mapping[state] = {
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "redirect_uri_provided_explicitly": str(params.redirect_uri_provided_explicitly),
            "client_id": client.client_id,
        }

        # Build GitHub authorization URL
        auth_url = (
            f"{self.settings.github_auth_url}"
            f"?client_id={self.settings.github_client_id}"
            f"&redirect_uri={self.settings.github_callback_path}"
            f"&scope={self.settings.github_scope}"
            f"&state={state}"
        )

        return auth_url

    async def handle_github_callback(self, code: str, state: str) -> str:
        """Handle GitHub OAuth callback."""
        state_data = self.state_mapping.get(state)
        if not state_data:
            raise HTTPException(400, "Invalid state parameter")

        redirect_uri = state_data["redirect_uri"]
        code_challenge = state_data["code_challenge"]
        redirect_uri_provided_explicitly = state_data["redirect_uri_provided_explicitly"] == "True"
        client_id = state_data["client_id"]

        # Exchange code for token with GitHub
        async with create_mcp_http_client() as client:
            response = await client.post(
                self.settings.github_token_url,
                data={
                    "client_id": self.settings.github_client_id,
                    "client_secret": self.settings.github_client_secret,
                    "code": code,
                    "redirect_uri": self.settings.github_callback_path,
                },
                headers={"Accept": "application/json"},
            )

            if response.status_code != 200:
                raise HTTPException(400, "Failed to exchange code for token")

            data = response.json()

            if "error" in data:
                raise HTTPException(400, data.get("error_description", data["error"]))

            github_token = data["access_token"]

            # Create MCP authorization code
            new_code = f"mcp_{secrets.token_hex(16)}"
            auth_code = AuthorizationCode(
                code=new_code,
                client_id=client_id,
                redirect_uri=AnyHttpUrl(redirect_uri),
                redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
                expires_at=time.time() + 300,
                scopes=[self.settings.mcp_scope],
                code_challenge=code_challenge,
            )
            self.auth_codes[new_code] = auth_code

            # Store GitHub token - we'll map the MCP token to this later
            self.tokens[github_token] = AccessToken(
                token=github_token,
                client_id=client_id,
                scopes=[self.settings.github_scope],
                expires_at=None,
            )

        del self.state_mapping[state]
        return construct_redirect_uri(redirect_uri, code=new_code, state=state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        """Load an authorization code."""
        return self.auth_codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Exchange authorization code for tokens."""
        if authorization_code.code not in self.auth_codes:
            raise ValueError("Invalid authorization code")

        # Generate MCP access token
        mcp_token = f"mcp_{secrets.token_hex(32)}"

        # Store MCP token
        self.tokens[mcp_token] = AccessToken(
            token=mcp_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + 3600,
        )

        # Find GitHub token for this client
        github_token = next(
            (
                token
                for token, data in self.tokens.items()
                # see https://github.blog/engineering/platform-security/behind-githubs-new-authentication-token-formats/
                # which you get depends on your GH app setup.
                if (token.startswith("ghu_") or token.startswith("gho_")) and data.client_id == client.client_id
            ),
            None,
        )

        # Store mapping between MCP token and GitHub token
        if github_token:
            self.token_mapping[mcp_token] = github_token

        del self.auth_codes[authorization_code.code]

        return OAuthToken(
            access_token=mcp_token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(authorization_code.scopes),
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Load and validate an access token."""
        access_token = self.tokens.get(token)
        if not access_token:
            return None

        # Check if expired
        if access_token.expires_at and access_token.expires_at < time.time():
            del self.tokens[token]
            return None

        return access_token

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        """Load a refresh token - not supported."""
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchange refresh token"""
        raise NotImplementedError("Not supported")

    async def exchange_token(
        self,
        client: OAuthClientInformationFull,
        subject_token: str,
        subject_token_type: str,
        actor_token: str | None,
        actor_token_type: str | None,
        scope: list[str] | None,
        audience: str | None,
        resource: str | None,
    ) -> OAuthToken:
        """Exchange an external token for an MCP access token."""
        raise NotImplementedError("Token exchange is not supported")

    async def exchange_client_credentials(self, client: OAuthClientInformationFull, scopes: list[str]) -> OAuthToken:
        """Exchange client credentials for an access token."""
        token = f"mcp_{secrets.token_hex(32)}"
        self.tokens[token] = AccessToken(
            token=token,
            client_id=client.client_id,
            scopes=scopes,
            expires_at=int(time.time()) + 3600,
        )
        return OAuthToken(
            access_token=token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(scopes),
        )

    async def revoke_token(self, token: str, token_type_hint: str | None = None) -> None:
        """Revoke a token."""
        if token in self.tokens:
            del self.tokens[token]


def create_simple_mcp_server(settings: ServerSettings) -> FastMCP:
    """Create a simple FastMCP server with GitHub OAuth."""
    oauth_provider = SimpleGitHubOAuthProvider(settings)

    auth_settings = AuthSettings(
        issuer_url=settings.server_url,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[settings.mcp_scope],
            default_scopes=[settings.mcp_scope],
        ),
        required_scopes=[settings.mcp_scope],
# =======
# def create_resource_server(settings: ResourceServerSettings) -> FastMCP:
#     """
#     Create MCP Resource Server with token introspection.

#     This server:
#     1. Provides protected resource metadata (RFC 9728)
#     2. Validates tokens via Authorization Server introspection
#     3. Serves MCP tools and resources
#     """
#     # Create token verifier for introspection with RFC 8707 resource validation
#     token_verifier = IntrospectionTokenVerifier(
#         introspection_endpoint=settings.auth_server_introspection_endpoint,
#         server_url=str(settings.server_url),
#         validate_resource=settings.oauth_strict,  # Only validate when --oauth-strict is set
# >>>>>>> main
    )

    # Create FastMCP server as a Resource Server
    app = FastMCP(
        name="MCP Resource Server",
        instructions="Resource Server that validates tokens via Authorization Server introspection",
        host=settings.host,
        port=settings.port,
        debug=True,
        # Auth configuration for RS mode
        token_verifier=token_verifier,
        auth=AuthSettings(
            issuer_url=settings.auth_server_url,
            required_scopes=[settings.mcp_scope],
            resource_server_url=settings.server_url,
        ),
    )

    async def get_github_user_data() -> dict[str, Any]:
        """
        Get GitHub user data via Authorization Server proxy endpoint.

        This avoids exposing GitHub tokens to the Resource Server.
        The Authorization Server handles the GitHub API call and returns the data.
        """
        access_token = get_access_token()
        if not access_token:
            raise ValueError("Not authenticated")

        # Call Authorization Server's GitHub proxy endpoint
        async with httpx.AsyncClient() as client:
            response = await client.get(
                settings.auth_server_github_user_endpoint,
                headers={
                    "Authorization": f"Bearer {access_token.token}",
                },
            )

            if response.status_code != 200:
                raise ValueError(f"GitHub user data fetch failed: {response.status_code} - {response.text}")

            return response.json()

    @app.tool()
    async def get_user_profile() -> dict[str, Any]:
        """
        Get the authenticated user's GitHub profile information.

        This tool requires the 'user' scope and demonstrates how Resource Servers
        can access user data without directly handling GitHub tokens.
        """
        return await get_github_user_data()

    @app.tool()
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
    """
    Run the MCP Resource Server.

    This server:
    - Provides RFC 9728 Protected Resource Metadata
    - Validates tokens via Authorization Server introspection
    - Serves MCP tools requiring authentication

    Must be used with a running Authorization Server.
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
            auth_server_introspection_endpoint=f"{auth_server}/introspect",
            auth_server_github_user_endpoint=f"{auth_server}/github/user",
            oauth_strict=oauth_strict,
        )
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Make sure to provide a valid Authorization Server URL")
        return 1

    try:
        mcp_server = create_resource_server(settings)

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
        logger.info("   ├─ get_user_profile() - Get GitHub user profile")
        logger.info("   └─ get_user_info() - Get authentication status")
        logger.info("")
        logger.info("🔍 Tokens validated via Authorization Server introspection")
        logger.info("📱 Clients discover Authorization Server via Protected Resource Metadata")
        logger.info("=" * 80)

        # Run the server - this should block and keep running
        mcp_server.run(transport=transport)
        logger.info("Server stopped")
        return 0
    except Exception as e:
        logger.error(f"Server error: {e}")
        logger.exception("Exception details:")
        return 1


if __name__ == "__main__":
    main()  # type: ignore[call-arg]
