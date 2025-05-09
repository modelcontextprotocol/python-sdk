"""Simple MCP Server with GitHub OAuth Authentication."""

import logging
import secrets
import time
from typing import Any

import click
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response, HTMLResponse

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp.server import FastMCP
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


class ServerSettings(BaseSettings):
    """Settings for the simple GitHub MCP server."""

    model_config = SettingsConfigDict(env_prefix="MCP_GITHUB_")

    # Server settings
    host: str = "localhost"
    port: int = 8000
    server_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")

    # GitHub OAuth settings - MUST be provided via environment variables
    github_client_id: str  # Type: MCP_GITHUB_GITHUB_CLIENT_ID env var
    github_client_secret: str  # Type: MCP_GITHUB_GITHUB_CLIENT_SECRET env var
    github_callback_path: str = "http://localhost:8000/github/callback"

    # GitHub OAuth URLs
    github_auth_url: str = "https://github.com/login/oauth/authorize"
    github_token_url: str = "https://github.com/login/oauth/access_token"

    mcp_scope: str = "user"
    github_scope: str = "read:user"

    def __init__(self, **data):
        """Initialize settings with values from environment variables.

        Note: github_client_id and github_client_secret are required but can be
        loaded automatically from environment variables (MCP_GITHUB_GITHUB_CLIENT_ID
        and MCP_GITHUB_GITHUB_CLIENT_SECRET) and don't need to be passed explicitly.
        """
        super().__init__(**data)


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

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Generate an authorization URL for GitHub OAuth flow."""
        state = params.state or secrets.token_hex(16)

        # Store the state mapping
        self.state_mapping[state] = {
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "redirect_uri_provided_explicitly": str(
                params.redirect_uri_provided_explicitly
            ),
            "client_id": client.client_id,
        }

        # Return our custom consent endpoint, which will then redirect to Github

        # Extract scopes - use default MCP scope if none provided
        scopes = params.scopes or [self.settings.mcp_scope]
        scopes_string = " ".join(scopes) if isinstance(scopes, list) else str(scopes)

        consent_params = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "state": state,
            "scopes": scopes_string,
            "code_challenge": params.code_challenge or "",
            "response_type": "code"
        }

        consent_url = f"{self.settings.server_url}consent?{urlencode(consent_params)}"
        return consent_url

    async def handle_github_callback(self, code: str, state: str) -> str:
        """Handle GitHub OAuth callback."""
        state_data = self.state_mapping.get(state)
        if not state_data:
            raise HTTPException(400, "Invalid state parameter")

        redirect_uri = state_data["redirect_uri"]
        code_challenge = state_data["code_challenge"]
        redirect_uri_provided_explicitly = (
            state_data["redirect_uri_provided_explicitly"] == "True"
        )
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
                if (token.startswith("ghu_") or token.startswith("gho_"))
                and data.client_id == client.client_id
            ),
            None,
        )

        # Store mapping between MCP token and GitHub token
        if github_token:
            self.token_mapping[mcp_token] = github_token

        del self.auth_codes[authorization_code.code]

        return OAuthToken(
            access_token=mcp_token,
            token_type="bearer",
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

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
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

    async def revoke_token(
        self, token: str, token_type_hint: str | None = None
    ) -> None:
        """Revoke a token."""
        if token in self.tokens:
            del self.tokens[token]


class ConsentHandler:

    def __init__(self, provider: SimpleGitHubOAuthProvider, settings: ServerSettings, path: str):
        self.provider: SimpleGitHubOAuthProvider = provider
        self.settings: ServerSettings = settings
        self.client_consent: dict[str, bool] = {}
        self.path = path

    async def handle(self, request: Request) -> Response:
        # This handles both showing the consent form (GET) and processing consent (POST)
        if request.method == "GET":
            # Show consent form
            return await self._show_consent_form(request)
        elif request.method == "POST":
            # Process consent
            return await self._process_consent(request)
        else:
            return HTMLResponse(status_code=405, content="Method not allowed")

    async def _show_consent_form(self, request: Request) -> HTMLResponse:
        client_id = request.query_params.get("client_id", "")
        redirect_uri = request.query_params.get("redirect_uri", "")
        # TODO: address csrf
        state = request.query_params.get("state", "")
        scopes = request.query_params.get("scopes", "")
        code_challenge = request.query_params.get("code_challenge", "")
        response_type = request.query_params.get("response_type", "")

        # Get client info to display client_name
        client_name = client_id  # Default to client_id if we can't get the client
        if client_id:
            client = await self.provider.get_client(client_id)
            if client and hasattr(client, 'client_name'):
                client_name = client.client_name

        target_url = self.path

        # TODO: allow skipping consent if we've already approved this client ID

        # Create a simple consent form
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Authorization Required</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .consent-form {{
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            width: 100%;
            max-width: 400px;
        }}
        h1 {{
            margin: 0 0 20px 0;
            font-size: 24px;
            font-weight: 600;
        }}
        p {{
            margin-bottom: 20px;
            color: #666;
        }}
        .client-info {{
            background: #f8f8f8;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 20px;
        }}
        .scopes {{
            margin-bottom: 20px;
        }}
        .scope-item {{
            padding: 8px 0;
            border-bottom: 1px solid #eee;
        }}
        .scope-item:last-child {{
            border-bottom: none;
        }}
        .button-group {{
            display: flex;
            gap: 10px;
        }}
        button {{
            flex: 1;
            padding: 10px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
        }}
        .approve {{
            background: #0366d6;
            color: white;
        }}
        .deny {{
            background: #f6f8fa;
            color: #24292e;
            border: 1px solid #d1d5da;
        }}
        button:hover {{
            opacity: 0.9;
        }}
    </style>
</head>
<body>
    <div class="consent-form">
        <h1>Authorization Request</h1>
        <p>The application <strong>{client_name}</strong> is requesting access to your resources.</p>

        <div class="client-info">
            <strong>Application Name:</strong> {client_name}<br>
            <strong>Client ID:</strong> {client_id}<br>
            <strong>Redirect URI:</strong> {redirect_uri}
        </div>

        <div class="scopes">
            <strong>Requested Permissions:</strong>
            {self._format_scopes(scopes)}
        </div>

        <form method="POST" action="{target_url}">
            <input type="hidden" name="client_id" value="{client_id}">
            <input type="hidden" name="redirect_uri" value="{redirect_uri}">
            <input type="hidden" name="state" value="{state}">
            <input type="hidden" name="scopes" value="{scopes}">
            <input type="hidden" name="code_challenge" value="{code_challenge}">
            <input type="hidden" name="response_type" value="{response_type}">

            <div class="button-group">
                <button type="submit" name="action" value="approve" class="approve">Approve</button>
                <button type="submit" name="action" value="deny" class="deny">Deny</button>
            </div>
        </form>
    </div>
</body>
</html>
"""
        return HTMLResponse(content=html_content)

    async def _process_consent(self, request: Request) -> RedirectResponse | HTMLResponse:
        form_data = await request.form()
        action = form_data.get("action")
        state = form_data.get("state")

        if action == "approve":
            # Grant consent and continue with authorization
            client_id = form_data.get("client_id")
            if client_id:
                client = await self.provider.get_client(client_id)
                if client:
                    self.client_consent[client.client_id] = True

            auth_url = (
                f"{self.settings.github_auth_url}"
                f"?client_id={self.settings.github_client_id}"
                f"&redirect_uri={self.settings.github_callback_path}"
                f"&scope={self.settings.github_scope}"
                f"&state={state}"
            )

            return RedirectResponse(
                # TODO: get this passed in
                url=auth_url,
                status_code=302,
                headers={"Cache-Control": "no-store"},
            )
        else:
            # User denied consent
            redirect_uri = form_data.get("redirect_uri")
            state = form_data.get("state")

            error_params = {
                "error": "access_denied",
                "error_description": "User denied the authorization request"
            }
            if state:
                error_params["state"] = state

            if redirect_uri:
                return RedirectResponse(
                    url=f"{redirect_uri}?{urlencode(error_params)}",
                    status_code=302,
                    headers={"Cache-Control": "no-store"},
                )
            else:
                return HTMLResponse(
                    status_code=400,
                    content=f"Access denied: {error_params['error_description']}"
                )

    def _format_scopes(self, scopes: str) -> str:
        if not scopes:
            return "<p>No specific permissions requested</p>"

        scope_list = scopes.split()
        if not scope_list:
            return "<p>No specific permissions requested</p>"

        scope_html = ""
        for scope in scope_list:
            scope_html += f'<div class="scope-item">{scope}</div>'

        return scope_html




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
    )

    app = FastMCP(
        name="Simple GitHub MCP Server",
        instructions="A simple MCP server with GitHub OAuth authentication",
        auth_server_provider=oauth_provider,
        host=settings.host,
        port=settings.port,
        debug=True,
        auth=auth_settings,
    )

    consent_path = "/consent"
    consent_handler = ConsentHandler(provider=oauth_provider, settings=settings, path=consent_path)

    @app.custom_route(consent_path, methods=["GET", "POST"])
    async def example_consent_handler(request: Request) -> Response:
        return await consent_handler.handle(request)

    @app.custom_route("/github/callback", methods=["GET"])
    async def github_callback_handler(request: Request) -> Response:
        """Handle GitHub OAuth callback."""
        code = request.query_params.get("code")
        state = request.query_params.get("state")

        if not code or not state:
            raise HTTPException(400, "Missing code or state parameter")

        try:
            redirect_uri = await oauth_provider.handle_github_callback(code, state)
            return RedirectResponse(status_code=302, url=redirect_uri)
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Unexpected error", exc_info=e)
            return JSONResponse(
                status_code=500,
                content={
                    "error": "server_error",
                    "error_description": "Unexpected error",
                },
            )

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
        github_token = get_github_token()

        async with create_mcp_http_client() as client:
            response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )

            if response.status_code != 200:
                raise ValueError(
                    f"GitHub API error: {response.status_code} - {response.text}"
                )

            return response.json()

    return app


@click.command()
@click.option("--port", default=8000, help="Port to listen on")
@click.option("--host", default="localhost", help="Host to bind to")
def main(port: int, host: str) -> int:
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
    mcp_server.run(transport="sse")
    return 0
