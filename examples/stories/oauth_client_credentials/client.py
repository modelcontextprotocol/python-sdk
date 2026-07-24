"""HTTP-only: ``build_auth`` returns a ``ClientCredentialsOAuthProvider``; ``whoami`` round-trips client_id + scopes."""

import httpx2

from mcp.client import Client
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
from stories._harness import Target, run_client

# MCP_URL pins the resource to :8000, and the server side builds its PRM/AS metadata from
# the same constant — run the server on 8000 or the discovery chain points at the wrong origin.
from stories._shared.auth import MCP_URL, InMemoryTokenStorage

from .server import DEMO_CLIENT_ID, DEMO_CLIENT_SECRET, DEMO_SCOPE


def build_auth(_http: httpx2.AsyncClient) -> httpx2.Auth:
    """The ``httpx2.Auth`` for the ``client_credentials`` grant — five lines of provider config.

    The SDK then handles 401 → RFC 9728 PRM → RFC 8414 AS-metadata discovery → token POST →
    Bearer attachment automatically. ``Client(url)`` has no ``auth=`` passthrough yet, so the
    harness threads this onto the transport's ``httpx2.AsyncClient`` and hands ``main`` the
    already-authed ``target``.
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
