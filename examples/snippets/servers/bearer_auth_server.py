"""Run from the repository root:
uv run examples/snippets/servers/bearer_auth_server.py
"""

from pydantic import AnyHttpUrl

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer


class StaticTokenVerifier(TokenVerifier):
    """Accept a single bearer token for demonstration purposes."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if token != "secret-token":
            return None

        return AccessToken(
            token=token,
            client_id="demo-client",
            scopes=["user"],
        )


mcp = MCPServer(
    "Bearer auth demo",
    token_verifier=StaticTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        resource_server_url=AnyHttpUrl("http://localhost:8000"),
        required_scopes=["user"],
    ),
)


@mcp.tool()
async def whoami() -> str:
    """Return the authenticated client id."""
    access_token = get_access_token()
    if access_token is None:
        # The auth middleware rejects unauthenticated requests before tools run.
        raise ValueError("No access token found")

    return f"Authenticated as {access_token.client_id}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
