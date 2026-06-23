"""Connect with ``ClientCredentialsOAuthProvider``; assert ``whoami`` round-trips client_id + scopes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from mcp.client import Client
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.version import LATEST_MODERN_VERSION
from stories._harness import argv_after, run_client
from stories._shared.auth import MCP_URL, InMemoryTokenStorage

from .server import DEMO_CLIENT_ID, DEMO_CLIENT_SECRET, DEMO_SCOPE


def build_auth(_http: httpx.AsyncClient) -> httpx.Auth:
    """The ``httpx.Auth`` for the ``client_credentials`` grant — five lines of provider config.

    The SDK then handles 401 → RFC 9728 PRM → RFC 8414 AS-metadata discovery → token POST →
    Bearer attachment automatically. Signature satisfies the harness ``AuthBuilder`` hook.
    """
    return ClientCredentialsOAuthProvider(
        server_url=MCP_URL,
        storage=InMemoryTokenStorage(),
        client_id=DEMO_CLIENT_ID,
        client_secret=DEMO_CLIENT_SECRET,
        scopes=DEMO_SCOPE,
    )


async def scenario(client: Client) -> None:
    listed = await client.list_tools()
    assert [t.name for t in listed.tools] == ["whoami"]

    result = await client.call_tool("whoami", {})
    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["client_id"] == DEMO_CLIENT_ID, result
    assert DEMO_SCOPE in result.structured_content["scopes"]


if __name__ == "__main__":
    url = argv_after("--http", default=MCP_URL)

    # Client(url) has no auth= passthrough yet, so build the httpx → streamable_http_client
    # → Client chain by hand and thread the auth onto httpx.
    @asynccontextmanager
    async def _connect(**kw: Any) -> AsyncIterator[Client]:
        async with httpx.AsyncClient() as http:
            http.auth = build_auth(http)
            async with Client(streamable_http_client(url, http_client=http), **kw) as client:
                yield client

    run_client(scenario, connect=_connect, mode=LATEST_MODERN_VERSION)
