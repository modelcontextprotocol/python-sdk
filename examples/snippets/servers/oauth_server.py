"""Run from the repository root:
uv run examples/snippets/servers/oauth_server.py
"""

from pydantic import AnyHttpUrl

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer


class SimpleTokenVerifier(TokenVerifier):
    """Simple token verifier for demonstration."""

    async def verify_token(self, token: str) -> AccessToken | None:
        pass  # This is where you would implement actual token validation


# Create MCPServer instance as a Resource Server
mcp = MCPServer(
    "Weather Service",
    # Token verifier for authentication
    token_verifier=SimpleTokenVerifier(),
    # Auth settings for RFC 9728 Protected Resource Metadata.
    # `resource_server_url` MUST be the full public URL of the MCP endpoint, including
    # the transport path (e.g. `/mcp` for streamable-http, `/sse` for sse). RFC 9728
    # section 3.3 requires strict equality between the client's resource identifier and
    # the `resource` value advertised in the protected resource metadata.
    auth=AuthSettings(
        issuer_url=AnyHttpUrl("https://auth.example.com"),  # Authorization Server URL
        resource_server_url=AnyHttpUrl("http://localhost:3001/mcp"),  # Public MCP endpoint URL
        required_scopes=["user"],
    ),
)


@mcp.tool()
async def get_weather(city: str = "London") -> dict[str, str]:
    """Get weather data for a city"""
    return {
        "city": city,
        "temperature": "22",
        "condition": "Partly cloudy",
        "humidity": "65%",
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http", json_response=True)
