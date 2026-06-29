"""HTTP-only: `build_auth` returns a `ClientCredentialsOAuthProvider`; `whoami` round-trips client_id + scopes."""

import httpx

from mcp.client import Client
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
from stories._harness import Target, run_client

# The server builds PRM/AS metadata from this same MCP_URL — run it on :8000 or discovery points at the wrong origin.
from stories._shared.auth import MCP_URL, InMemoryTokenStorage

from .server import DEMO_CLIENT_ID, DEMO_CLIENT_SECRET, DEMO_SCOPE


def build_auth(_http: httpx.AsyncClient) -> httpx.Auth:
    """Build the `httpx.Auth` for the `client_credentials` grant.

    The SDK drives 401 → RFC 9728 PRM → RFC 8414 AS metadata → token POST → Bearer. `Client(url)` has
    no `auth=` passthrough yet, so the harness threads this onto the transport's `httpx.AsyncClient`.
    """
    return ClientCredentialsOAuthProvider(
        server_url=MCP_URL,
        storage=InMemoryTokenStorage(),
        client_id=DEMO_CLIENT_ID,
        client_secret=DEMO_CLIENT_SECRET,
        scopes=DEMO_SCOPE,
    )


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
        listed = await client.list_tools()
        assert [t.name for t in listed.tools] == ["whoami"]

        result = await client.call_tool("whoami", {})
        assert not result.is_error
        assert result.structured_content is not None
        assert result.structured_content["client_id"] == DEMO_CLIENT_ID, result
        assert DEMO_SCOPE in result.structured_content["scopes"]


if __name__ == "__main__":
    run_client(main)
