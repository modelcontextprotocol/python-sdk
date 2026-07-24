"""Client side of SEP-990 (enterprise IdP policy controls).

`IdentityAssertionOAuthProvider` presents an Identity Assertion Authorization Grant (ID-JAG) issued
by the enterprise IdP to the MCP authorization server using the RFC 7523 jwt-bearer grant
(`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, ID-JAG as `assertion`), and receives an
MCP access token. No browser redirect or dynamic client registration is involved.

Obtaining the ID-JAG (logging into the IdP and the leg-1 exchange against it) is deployment-specific
and out of scope for the SDK; supply it through the `assertion_provider` callback. The callback
receives the authorization server's issuer (the ID-JAG `aud`) and the MCP server's resource
identifier (the ID-JAG `resource` claim). SEP-990 requires a confidential client, so a client secret
is mandatory, and `issuer` is the authorization server the credentials are provisioned for - the
provider fetches metadata from that issuer's well-known and never asks the resource server which AS
to use.
"""

import asyncio

import httpx2

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
    """Return the ID-JAG to present.

    `audience` is the MCP authorization server's issuer (the ID-JAG `aud` claim); `resource` is the
    MCP server's RFC 9728 identifier (the ID-JAG `resource` claim, which the AS audience-restricts
    the issued token against). In production this exchanges the user's IdP ID token for an ID-JAG
    against the enterprise identity provider.
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

    async with httpx2.AsyncClient(auth=oauth_auth, follow_redirects=True) as http_client:
        async with streamable_http_client("http://localhost:8001/mcp", http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print(f"Available tools: {[tool.name for tool in tools.tools]}")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
