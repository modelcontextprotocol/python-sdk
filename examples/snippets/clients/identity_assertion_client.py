"""Client side of SEP-990 (enterprise IdP policy controls).

`IdentityAssertionOAuthProvider` presents an enterprise-IdP-issued Identity Assertion Authorization
Grant (ID-JAG) to the MCP authorization server via the RFC 7523 jwt-bearer grant to obtain an MCP
access token - no browser redirect or dynamic client registration. Obtaining the ID-JAG is
deployment-specific and out of SDK scope; supply it via the `assertion_provider` callback. SEP-990
requires a confidential client (client secret mandatory), and the provider fetches AS metadata from
`issuer`, never asking the resource server which AS to use.
"""

import asyncio

import httpx

from mcp import ClientSession
from mcp.client.auth.extensions.identity_assertion import IdentityAssertionOAuthProvider
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


async def fetch_id_jag(audience: str, resource: str) -> str:
    """Return the ID-JAG to present (in production: exchange the user's IdP ID token at the enterprise IdP).

    `audience` is the authorization server's issuer (the ID-JAG `aud` claim); `resource` is the MCP
    server's RFC 9728 identifier (the ID-JAG `resource` claim the issued token is audience-restricted to).
    """
    raise NotImplementedError("Obtain the ID-JAG from your enterprise identity provider")


async def main() -> None:
    oauth_auth = IdentityAssertionOAuthProvider(
        server_url="http://localhost:8001/mcp",
        storage=InMemoryTokenStorage(),
        client_id="enterprise-mcp-client",
        client_secret="enterprise-mcp-secret",
        issuer="http://localhost:8001",
        assertion_provider=fetch_id_jag,
        scope="user",
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
