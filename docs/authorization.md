# Authorization

MCP servers that expose protected tools can validate bearer tokens by passing a
`TokenVerifier` and `AuthSettings` when creating the server. The SDK applies the
same bearer-token middleware to Streamable HTTP and SSE transports, so tool
handlers do not need to inspect the `Authorization` header themselves.

## Bearer Token Server

Use this pattern when you already have bearer tokens from an external
authorization server, API gateway, or another trusted issuer. The verifier owns
the token validation logic and returns an `AccessToken` only when the incoming
token is valid for this MCP server.

```python
from pydantic import AnyHttpUrl

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer


class StaticTokenVerifier(TokenVerifier):
    """Demo verifier. Replace this with your real token validation."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if token != "dev-token":
            return None

        return AccessToken(
            token=token,
            client_id="local-client",
            scopes=["tools:read"],
        )


mcp = MCPServer(
    "Protected Demo",
    token_verifier=StaticTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        resource_server_url=AnyHttpUrl("http://localhost:8000"),
        required_scopes=["tools:read"],
    ),
)


@mcp.tool()
async def protected_ping() -> str:
    """Return a message only for authenticated callers."""
    return "pong"


if __name__ == "__main__":
    mcp.run(transport="sse")
    # Or use Streamable HTTP:
    # mcp.run(transport="streamable-http")
```

Clients must send the token in the HTTP `Authorization` header:

```http
Authorization: Bearer dev-token
```

For the MCP Inspector, choose the matching transport, point it at the server
URL, and enter the bearer token in the Inspector's token field. With the default
paths, SSE uses `http://localhost:8000/sse` and Streamable HTTP uses
`http://localhost:8000/mcp`.

If the token is missing or invalid, the SDK returns `401 invalid_token`. If the
token is valid but does not include every `required_scopes` entry, the SDK
returns `403 insufficient_scope`.

!!! note

    The token string above is only a local development placeholder. Production
    verifiers should validate signed tokens, introspect opaque tokens, or call
    the appropriate authorization service instead of comparing against a hard
    coded value.
