import os
import secrets

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier

API_TOKEN = os.environ.get("NOTES_API_TOKEN") or secrets.token_urlsafe(32)


class PresharedTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        if secrets.compare_digest(token.encode(), API_TOKEN.encode()):
            return AccessToken(token=token, client_id="notes-client", scopes=[])
        return None


mcp = MCPServer("Notes", token_verifier=PresharedTokenVerifier())


@mcp.tool()
def whoami() -> str:
    """Report which client is calling."""
    token = get_access_token()
    if token is None:
        return "anonymous"
    return token.client_id
