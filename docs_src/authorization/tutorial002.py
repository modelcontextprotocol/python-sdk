from pydantic import AnyHttpUrl

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

KNOWN_TOKENS = {
    "alice-token": AccessToken(token="alice-token", client_id="alice", scopes=["notes:read"]),
}


class StaticTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        return KNOWN_TOKENS.get(token)


mcp = MCPServer(
    "Notes",
    token_verifier=StaticTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        resource_server_url=AnyHttpUrl("http://127.0.0.1:8000/mcp"),
        required_scopes=["notes:read"],
    ),
)


@mcp.tool()
def whoami() -> str:
    """Report which OAuth client is calling."""
    token = get_access_token()
    if token is None:
        return "anonymous"
    return f"{token.client_id} (scopes: {', '.join(token.scopes)})"
