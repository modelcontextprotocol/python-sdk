import httpx2

from mcp import Client
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class InMemoryTokenStorage:
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


oauth = ClientCredentialsOAuthProvider(
    server_url="http://localhost:8001/mcp",
    storage=InMemoryTokenStorage(),
    client_id="reporting-agent",
    client_secret="...",
    scopes="user",
)


async def main() -> None:
    async with httpx2.AsyncClient(auth=oauth, follow_redirects=True) as http_client:
        transport = streamable_http_client("http://localhost:8001/mcp", http_client=http_client)
        async with Client(transport) as client:
            result = await client.list_tools()
            print([tool.name for tool in result.tools])
