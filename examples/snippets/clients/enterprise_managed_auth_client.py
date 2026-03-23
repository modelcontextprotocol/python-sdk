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


async def discover_mcp_server_metadata(server_url: str) -> tuple[str, str]:
    """Discover MCP server's OAuth metadata and resource identifier.

    Returns:
        Tuple of (auth_issuer, resource_id)
    """
    from mcp.client.auth.utils import (
        build_oauth_authorization_server_metadata_discovery_urls,
        build_protected_resource_metadata_discovery_urls,
        handle_auth_metadata_response,
        handle_protected_resource_response,
    )

    async with httpx.AsyncClient() as client:
        # Step 1: Discover Protected Resource Metadata (PRM)
        prm_urls = build_protected_resource_metadata_discovery_urls(None, server_url)

        prm = None
        for url in prm_urls:
            response = await client.get(url)
            prm = await handle_protected_resource_response(response)
            if prm:
                break

        if not prm:
            raise ValueError("Could not discover Protected Resource Metadata")

        # Extract resource identifier and authorization server URL
        resource_id = str(prm.resource)
        auth_server_url = str(prm.authorization_servers[0]) if prm.authorization_servers else None

        # Step 2: Discover OAuth Authorization Server Metadata
        oauth_urls = build_oauth_authorization_server_metadata_discovery_urls(auth_server_url, server_url)

        oauth_metadata = None
        for url in oauth_urls:
            response = await client.get(url)
            ok, asm = await handle_auth_metadata_response(response)
            if ok and asm:
                oauth_metadata = asm
                break

        if not oauth_metadata or not oauth_metadata.issuer:
            raise ValueError("Could not discover OAuth metadata or issuer")

        auth_issuer = str(oauth_metadata.issuer)

        return auth_issuer, resource_id


async def main() -> None:
    """Example demonstrating enterprise managed authorization with MCP."""
    server_url = "https://mcp-server.example.com"

    # Step 1: Get ID token from your IdP (e.g., Okta, Azure AD)
    id_token = await get_id_token_from_idp()

    # Step 2: Discover MCP server's OAuth metadata and resource identifier
    # This replaces hardcoding these values
    mcp_server_auth_issuer, mcp_server_resource_id = await discover_mcp_server_metadata(server_url)
    print(f"Discovered auth issuer: {mcp_server_auth_issuer}")
    print(f"Discovered resource ID: {mcp_server_resource_id}")

    # Step 3: Configure token exchange parameters using discovered values
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=id_token,
        mcp_server_auth_issuer=mcp_server_auth_issuer,
        mcp_server_resource_id=mcp_server_resource_id,
        scope="mcp:tools mcp:resources",  # Optional scopes
    )

    # Step 4: Create enterprise auth provider
    enterprise_auth = EnterpriseAuthOAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="Enterprise MCP Client",
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
            grant_types=["urn:ietf:params:oauth:grant-type:jwt-bearer"],
            response_types=["token"],
        ),
        storage=SimpleTokenStorage(),
        idp_token_endpoint="https://your-idp.com/oauth2/v1/token",  # Your IdP's token endpoint
        token_exchange_params=token_exchange_params,
        # Optional: IdP client credentials if your IdP requires client authentication for token exchange
        # idp_client_id="your-idp-client-id",
        # idp_client_secret="your-idp-client-secret",
    )

    # Step 5: Create authenticated HTTP client
    # The auth provider automatically handles the two-step token exchange:
    # 1. ID Token -> ID-JAG (via IDP)
    # 2. ID-JAG -> Access Token (via MCP server)
    client = httpx.AsyncClient(auth=enterprise_auth, timeout=30.0)

    # Step 6: Connect to MCP server with authenticated client
    async with streamable_http_client(url=server_url, http_client=client) as (read, write):
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
    """Advanced example showing manual token exchange.

    Use cases for manual token exchange:
    - Testing and debugging: Inspect ID-JAG claims before exchanging for access token
    - Token caching: Store and reuse ID-JAG across multiple MCP server connections
    - Custom error handling: Implement specific retry logic for each token exchange step
    - Monitoring: Log token exchange metrics and performance
    - Token introspection: Validate ID-JAG structure before sending to MCP server
    """
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

    # Manual token exchange (useful for debugging, caching, custom error handling, etc.)
    async with httpx.AsyncClient() as client:
        # Step 1: Exchange ID token for ID-JAG
        id_jag = await enterprise_auth.exchange_token_for_id_jag(client)
        # WARNING: Only log tokens in development/testing environments
        # In production, NEVER log tokens or token fragments as they are sensitive credentials
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
        # WARNING: In production, do not log token expiry or any token information
        print(f"Access token obtained, expires in: {access_token.expires_in}s")

        # Use the access token for API calls
        _ = {"Authorization": f"Bearer {access_token.access_token}"}
        # ... make authenticated requests with headers


async def token_refresh_example() -> None:
    """Example showing how to refresh tokens when they expire.

    When your access token expires, you need to obtain a fresh ID token
    from your enterprise IdP and use the refresh helper method.
    """
    # Initial setup
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

    _ = httpx.AsyncClient(auth=enterprise_auth, timeout=30.0)

    # Use the client for MCP operations...
    # ... time passes and token expires ...

    # When token expires, get a fresh ID token from your IdP
    new_id_token = await get_id_token_from_idp()

    # Refresh the authentication using the helper method
    await enterprise_auth.refresh_with_new_id_token(new_id_token)

    # Next API call will automatically use the refreshed tokens
    # No need to recreate the client or session


if __name__ == "__main__":
    asyncio.run(main())
