import time
import uuid

import httpx2
import jwt

from mcp import Client
from mcp.client.auth.extensions.identity_assertion import IdentityAssertionOAuthProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

IDP_SIGNING_KEY = "the-enterprise-idp-signing-key"


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


def idp_issue_id_jag(subject: str, audience: str, resource: str) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://idp.example.com",
        "sub": subject,
        "aud": audience,
        "client_id": "finance-agent",
        "resource": resource,
        "scope": "notes:read",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + 300,
    }
    return jwt.encode(claims, IDP_SIGNING_KEY, algorithm="HS256", headers={"typ": "oauth-id-jag+jwt"})


async def fetch_id_jag(audience: str, resource: str) -> str:
    return idp_issue_id_jag("alice@example.com", audience, resource)


oauth = IdentityAssertionOAuthProvider(
    server_url="http://localhost:8001/mcp",
    storage=InMemoryTokenStorage(),
    client_id="finance-agent",
    client_secret="finance-agent-secret",
    issuer="https://auth.example.com",
    assertion_provider=fetch_id_jag,
    scope="notes:read",
)


async def main() -> None:
    async with httpx2.AsyncClient(auth=oauth, follow_redirects=True) as http_client:
        transport = streamable_http_client("http://localhost:8001/mcp", http_client=http_client)
        async with Client(transport) as client:
            result = await client.list_tools()
            print([tool.name for tool in result.tools])
