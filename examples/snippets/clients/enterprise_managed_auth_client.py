import asyncio

import httpx
from pydantic import AnyUrl

from mcp import ClientSession
from mcp.client.auth import TokenStorage
from mcp.client.auth.extensions import (
    EnterpriseAuthOAuthClientProvider,
    TokenExchangeParameters,
)
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


# Placeholder function for IdP authentication
async def get_id_token_from_idp() -> str:
    """Placeholder function to get ID token from your IdP.

    In production, implement actual IdP authentication flow.
    """
    raise NotImplementedError("Implement your IdP authentication flow here")


# Define token storage implementation
class SimpleTokenStorage(TokenStorage):
    def __init__(self) -> None:
        self._tokens: OAuthToken | None = None
        self._client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info


async def main() -> None:
    """Example demonstrating enterprise managed authorization with MCP."""
    # Step 1: Get ID token from your IdP (e.g., Okta, Azure AD)
    id_token = await get_id_token_from_idp()

    # Step 2: Configure token exchange parameters
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example.com",  # MCP server's auth issuer
        mcp_server_resource_id="https://mcp-server.example.com",  # MCP server resource ID
        scope="mcp:tools mcp:resources",  # Optional scopes
    )

    # Step 3: Create enterprise auth provider
    enterprise_auth = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example.com",
        client_metadata=OAuthClientMetadata(
            client_name="Enterprise MCP Client",
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
            grant_types=["urn:ietf:params:oauth:grant-type:jwt-bearer"],
            response_types=["token"],
        ),
        storage=SimpleTokenStorage(),
        idp_token_endpoint="https://your-idp.com/oauth2/v1/token",  # Your IdP's token endpoint
        token_exchange_params=token_exchange_params,
    )

    # Step 4: Create authenticated HTTP client
    # The auth provider automatically handles the two-step token exchange:
    # 1. ID Token → ID-JAG (via IDP)
    # 2. ID-JAG → Access Token (via MCP server)
    client = httpx.AsyncClient(auth=enterprise_auth, timeout=30.0)

    # Step 5: Connect to MCP server with authenticated client
    async with streamable_http_client(url="https://mcp-server.example.com", http_client=client) as (
        read,
        write,
        _,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List available tools
            tools_result = await session.list_tools()
            print(f"Available tools: {[t.name for t in tools_result.tools]}")

            # Call a tool - auth tokens are automatically managed
            if tools_result.tools:
                tool_name = tools_result.tools[0].name
                result = await session.call_tool(tool_name, {})
                print(f"Tool result: {result.content}")

            # List available resources
            resources = await session.list_resources()
            for resource in resources.resources:
                print(f"Resource: {resource.uri}")


async def advanced_manual_flow() -> None:
    """Advanced example showing manual token exchange (for special use cases)."""
    id_token = await get_id_token_from_idp()

    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=id_token,
        mcp_server_auth_issuer="https://auth.mcp-server.example.com",
        mcp_server_resource_id="https://mcp-server.example.com",
    )

    enterprise_auth = EnterpriseAuthOAuthClientProvider(
        server_url="https://mcp-server.example.com",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
        ),
        storage=SimpleTokenStorage(),
        idp_token_endpoint="https://your-idp.com/oauth2/v1/token",
        token_exchange_params=token_exchange_params,
    )

    # Manual token exchange (for debugging or special use cases)
    async with httpx.AsyncClient() as client:
        # Step 1: Exchange ID token for ID-JAG
        id_jag = await enterprise_auth.exchange_token_for_id_jag(client)
        print(f"Obtained ID-JAG: {id_jag[:50]}...")

        # Step 2: Build JWT bearer grant request
        jwt_bearer_request = await enterprise_auth.exchange_id_jag_for_access_token(id_jag)
        print(f"Built JWT bearer grant request to: {jwt_bearer_request.url}")

        # Step 3: Execute the request to get access token
        response = await client.send(jwt_bearer_request)
        response.raise_for_status()
        token_data = response.json()

        access_token = OAuthToken(
            access_token=token_data["access_token"],
            token_type=token_data["token_type"],
            expires_in=token_data.get("expires_in"),
        )
        print(f"Access token obtained, expires in: {access_token.expires_in}s")

        # Use the access token for API calls
        _ = {"Authorization": f"Bearer {access_token.access_token}"}
        # ... make authenticated requests with headers


if __name__ == "__main__":
    asyncio.run(main())
