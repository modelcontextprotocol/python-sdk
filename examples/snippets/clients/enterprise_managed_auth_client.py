import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pydantic import AnyUrl

from mcp import ClientSession
from mcp.client.auth import OAuthTokenError, TokenStorage
from mcp.client.auth.extensions import (
    EnterpriseAuthOAuthClientProvider,
    TokenExchangeParameters,
)
from mcp.client.sse import sse_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from mcp.types import CallToolResult


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


def is_token_expired(access_token: OAuthToken) -> bool:
    """Check if the access token has expired."""
    if access_token.expires_in:
        # Calculate expiration time
        issued_at = datetime.now(timezone.utc)
        expiration_time = issued_at + timedelta(seconds=access_token.expires_in)
        return datetime.now(timezone.utc) >= expiration_time
    return False


async def refresh_access_token(
    enterprise_auth: EnterpriseAuthOAuthClientProvider,
    client: httpx.AsyncClient,
    id_token: str,
) -> OAuthToken:
    """Refresh the access token when it expires."""
    try:
        # Update token exchange parameters with fresh ID token
        enterprise_auth.token_exchange_params.subject_token = id_token

        # Re-exchange for new ID-JAG
        id_jag = await enterprise_auth.exchange_token_for_id_jag(client)

        # Get new access token
        access_token = await enterprise_auth.exchange_id_jag_for_access_token(client, id_jag)
        return access_token
    except Exception as e:
        print(f"Token refresh failed: {e}")
        # Re-authenticate with IdP if ID token is also expired
        id_token = await get_id_token_from_idp()
        return await refresh_access_token(enterprise_auth, client, id_token)


async def call_tool_with_retry(
    session: ClientSession,
    tool_name: str,
    arguments: dict[str, Any],
    enterprise_auth: EnterpriseAuthOAuthClientProvider,
    client: httpx.AsyncClient,
    id_token: str,
) -> CallToolResult | None:
    """Call a tool with automatic retry on token expiration."""
    max_retries = 1

    for attempt in range(max_retries + 1):
        try:
            result = await session.call_tool(tool_name, arguments)
            return result
        except OAuthTokenError:
            if attempt < max_retries:
                print("Token expired, refreshing...")
                # Refresh token and reconnect
                _access_token = await refresh_access_token(enterprise_auth, client, id_token)
                # Note: In production, you'd need to reconnect the session here
            else:
                raise
    return None


async def main() -> None:
    # Step 1: Get ID token from your IdP (example with Okta)
    id_token = await get_id_token_from_idp()  # Your IdP authentication

    # Step 2: Configure token exchange parameters
    token_exchange_params = TokenExchangeParameters.from_id_token(
        id_token=id_token,
        mcp_server_auth_issuer="https://your-idp.com",  # IdP issuer URL
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
        idp_token_endpoint="https://your-idp.com/oauth2/v1/token",
        token_exchange_params=token_exchange_params,
    )

    async with httpx.AsyncClient() as client:
        # Step 4: Exchange ID token for ID-JAG
        id_jag = await enterprise_auth.exchange_token_for_id_jag(client)
        print(f"Obtained ID-JAG: {id_jag[:50]}...")

        # Step 5: Exchange ID-JAG for access token
        access_token = await enterprise_auth.exchange_id_jag_for_access_token(client, id_jag)
        print(f"Access token obtained, expires in: {access_token.expires_in}s")

        # Step 6: Check if token is expired (for demonstration)
        if is_token_expired(access_token):
            print("Token is expired, refreshing...")
            access_token = await refresh_access_token(enterprise_auth, client, id_token)

        # Step 7: Use the access token to connect to MCP server
        headers = {"Authorization": f"Bearer {access_token.access_token}"}

        async with sse_client(url="https://mcp-server.example.com", headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call tools with automatic retry on token expiration
                result = await call_tool_with_retry(
                    session, "enterprise_tool", {"param": "value"}, enterprise_auth, client, id_token
                )
                if result:
                    print(f"Tool result: {result.content}")

                # List available resources
                resources = await session.list_resources()
                for resource in resources.resources:
                    print(f"Resource: {resource.uri}")


async def maintain_active_session(
    enterprise_auth: EnterpriseAuthOAuthClientProvider,
    mcp_server_url: str,
) -> None:
    """Maintain an active session with automatic token refresh."""
    id_token_var = await get_id_token_from_idp()

    async with httpx.AsyncClient() as client:
        while True:
            try:
                # Update token exchange params with current ID token
                enterprise_auth.token_exchange_params.subject_token = id_token_var

                # Get access token
                id_jag = await enterprise_auth.exchange_token_for_id_jag(client)
                access_token = await enterprise_auth.exchange_id_jag_for_access_token(client, id_jag)

                # Calculate refresh time (refresh before expiration)
                refresh_in = access_token.expires_in - 60 if access_token.expires_in else 300

                # Use the token for MCP operations
                headers = {"Authorization": f"Bearer {access_token.access_token}"}
                async with sse_client(mcp_server_url, headers=headers) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()

                        # Perform operations...
                        # Schedule refresh before token expires
                        await asyncio.sleep(refresh_in)

            except Exception as e:
                print(f"Session error: {e}")
                # Re-authenticate with IdP
                id_token_var = await get_id_token_from_idp()
                await asyncio.sleep(5)  # Wait before retry


if __name__ == "__main__":
    asyncio.run(main())
