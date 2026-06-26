"""Client side of SEP-990 (enterprise IdP policy controls).

`TokenExchangeOAuthProvider` exchanges a subject token issued by the enterprise IdP - the
Identity Assertion Authorization Grant (ID-JAG) - for an MCP access token, using the RFC 8693
token-exchange grant at the MCP authorization server's token endpoint. No browser redirect or
dynamic client registration is involved.

Obtaining the ID-JAG (logging into the IdP and performing the first exchange against it) is
deployment-specific and out of scope for the SDK; supply it through the `subject_token_provider`
callback. The callback receives the authorization server's issuer identifier as its audience.
"""

import asyncio

import httpx

from mcp import ClientSession
from mcp.client.auth.extensions.token_exchange import TokenExchangeOAuthProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class InMemoryTokenStorage:
    """Demo in-memory token storage."""

    def __init__(self) -> None:
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


async def fetch_id_jag(audience: str) -> str:
    """Return the ID-JAG to exchange.

    `audience` is the MCP authorization server's issuer identifier; the returned ID-JAG must
    carry it as the `aud` claim. In production this exchanges the user's IdP ID token for an
    ID-JAG against the enterprise identity provider.
    """
    raise NotImplementedError("Obtain the ID-JAG from your enterprise identity provider")


async def main() -> None:
    oauth_auth = TokenExchangeOAuthProvider(
        server_url="http://localhost:8001/mcp",
        storage=InMemoryTokenStorage(),
        client_id="enterprise-mcp-client",
        subject_token_provider=fetch_id_jag,
        scopes="user",
    )

    async with httpx.AsyncClient(auth=oauth_auth, follow_redirects=True) as http_client:
        async with streamable_http_client("http://localhost:8001/mcp", http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print(f"Available tools: {[tool.name for tool in tools.tools]}")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
