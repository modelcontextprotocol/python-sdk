"""Run from the `examples/snippets` directory: uv run oauth-client

Requires a running MCP resource server; see examples/servers/simple-auth/README.md.
"""

import asyncio
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import AnyUrl

from mcp import ClientSession
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


class InMemoryTokenStorage(TokenStorage):
    """Demo-only storage; production clients should persist tokens securely."""

    def __init__(self):
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


async def handle_redirect(auth_url: str) -> None:
    print(f"Visit: {auth_url}")


async def handle_callback() -> AuthorizationCodeResult:
    callback_url = input("Paste callback URL: ")
    params = parse_qs(urlparse(callback_url).query)
    return AuthorizationCodeResult(
        code=params["code"][0],
        state=params.get("state", [None])[0],
        iss=params.get("iss", [None])[0],
    )


async def main():
    oauth_auth = OAuthClientProvider(
        server_url="http://localhost:8001",
        client_metadata=OAuthClientMetadata(
            client_name="Example MCP Client",
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="user",
        ),
        storage=InMemoryTokenStorage(),
        redirect_handler=handle_redirect,
        callback_handler=handle_callback,
    )

    async with httpx.AsyncClient(auth=oauth_auth, follow_redirects=True) as custom_client:
        async with streamable_http_client("http://localhost:8001/mcp", http_client=custom_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                print(f"Available tools: {[tool.name for tool in tools.tools]}")

                resources = await session.list_resources()
                print(f"Available resources: {[r.uri for r in resources.resources]}")


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
