"""Resource-server-only bearer auth: ``TokenVerifier`` + ``AuthSettings`` → 401/PRM/principal."""

import time

from pydantic import AnyHttpUrl
from starlette.applications import Starlette

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from stories._hosting import NO_DNS_REBIND, run_app_from_args

ISSUER = "https://auth.example.com"
RESOURCE_URL = "http://127.0.0.1:8000/mcp"
REQUIRED_SCOPE = "mcp:read"
DEMO_TOKEN = "demo-token"


class StaticTokenVerifier(TokenVerifier):
    """Accepts one hard-coded token. Replace with JWT verification or RFC 7662 introspection."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if token != DEMO_TOKEN:
            return None
        return AccessToken(
            token=token,
            client_id="demo-client",
            scopes=[REQUIRED_SCOPE],
            expires_at=int(time.time()) + 3600,
            subject="demo-user",
        )


def build_app() -> Starlette:
    mcp = MCPServer(
        "bearer-auth-example",
        token_verifier=StaticTokenVerifier(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(ISSUER),
            resource_server_url=AnyHttpUrl(RESOURCE_URL),
            required_scopes=[REQUIRED_SCOPE],
        ),
    )

    @mcp.tool(description="Return the authenticated principal.")
    def whoami() -> dict[str, str | list[str]]:
        token = get_access_token()
        assert token is not None  # the bearer gate guarantees this on the HTTP path
        return {"subject": token.subject or "", "client_id": token.client_id, "scopes": token.scopes}

    return mcp.streamable_http_app(transport_security=NO_DNS_REBIND)


if __name__ == "__main__":
    run_app_from_args(build_app)
