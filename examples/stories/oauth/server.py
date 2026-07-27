"""OAuth-protected MCP server: in-process AS + PRM + bearer-gated /mcp on one Starlette app — exports `build_app()`."""

from pydantic import BaseModel
from starlette.applications import Starlette

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver import MCPServer
from stories._hosting import NO_DNS_REBIND, run_app_from_args
from stories._shared.auth import InMemoryAuthorizationServerProvider, auth_settings


class Principal(BaseModel):
    client_id: str
    scopes: list[str]


def build_app() -> Starlette:
    # The provider is both the Authorization Server (DCR/authorize/token) and the
    # token store the bearer middleware validates against — one in-memory dict.
    provider = InMemoryAuthorizationServerProvider()

    # ``auth_server_provider=`` alone is enough — MCPServer derives a token verifier
    # from it (passing both trips the mutex guard).
    mcp = MCPServer(
        "oauth-example",
        auth=auth_settings(required_scopes=["mcp"]),
        auth_server_provider=provider,
    )

    @mcp.tool(description="Return the authenticated principal's client_id and granted scopes.")
    def whoami() -> Principal:
        token = get_access_token()
        assert token is not None
        return Principal(client_id=token.client_id, scopes=token.scopes)

    return mcp.streamable_http_app(transport_security=NO_DNS_REBIND)


if __name__ == "__main__":
    run_app_from_args(build_app)
