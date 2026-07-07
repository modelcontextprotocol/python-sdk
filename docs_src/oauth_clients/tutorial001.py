from urllib.parse import parse_qs, urlparse

from pydantic import AnyUrl

from mcp import Client, create_mcp_http_client
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


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


async def open_browser(authorization_url: str) -> None:
    print(f"Visit: {authorization_url}")


async def wait_for_callback() -> AuthorizationCodeResult:
    redirect_url = input("Paste the URL you were redirected to: ")
    params = parse_qs(urlparse(redirect_url).query)
    return AuthorizationCodeResult(
        code=params["code"][0],
        state=params["state"][0],
        iss=params["iss"][0] if "iss" in params else None,
    )


oauth = OAuthClientProvider(
    server_url="http://localhost:8001/mcp",
    client_metadata=OAuthClientMetadata(
        client_name="Bookshop Agent",
        redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        scope="user",
    ),
    storage=InMemoryTokenStorage(),
    redirect_handler=open_browser,
    callback_handler=wait_for_callback,
)


async def main() -> None:
    async with create_mcp_http_client(auth=oauth) as http_client:
        transport = streamable_http_client("http://localhost:8001/mcp", http_client=http_client)
        async with Client(transport) as client:
            result = await client.list_tools()
            print([tool.name for tool in result.tools])
