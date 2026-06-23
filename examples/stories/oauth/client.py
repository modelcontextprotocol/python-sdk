"""OAuth authorization-code flow: 401 → PRM → AS metadata → DCR → PKCE authorize → token → retry."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import httpx
from pydantic import AnyUrl

from mcp.client import Client
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata
from mcp.shared.version import LATEST_MODERN_VERSION
from stories._harness import AuthBuilder, Connect, argv_after, run_client
from stories._shared.auth import MCP_URL, REDIRECT_URI, HeadlessOAuth, InMemoryTokenStorage


def _auth_with(storage: InMemoryTokenStorage) -> AuthBuilder:
    """Build an ``OAuthClientProvider`` over ``storage``, completing the redirect headlessly."""

    def builder(http_client: httpx.AsyncClient) -> httpx.Auth:
        headless = HeadlessOAuth()
        headless.bind(http_client)
        return OAuthClientProvider(
            server_url=MCP_URL,
            client_metadata=OAuthClientMetadata(
                client_name="oauth-story-client",
                redirect_uris=[AnyUrl(REDIRECT_URI)],
                grant_types=["authorization_code", "refresh_token"],
            ),
            storage=storage,
            redirect_handler=headless.redirect_handler,
            callback_handler=headless.callback_handler,
        )

    return builder


def build_auth(http_client: httpx.AsyncClient) -> httpx.Auth:
    """Harness hook: fresh storage so each leg's first connection runs the full flow."""
    return _auth_with(InMemoryTokenStorage())(http_client)


async def scenario(client: Client, connect: Connect) -> None:
    # The harness entered ``client`` with auth=build_auth(...); the first /mcp request
    # 401'd and OAuthClientProvider walked PRM discovery → AS metadata → DCR → PKCE
    # authorize → token exchange → bearer retry — all inside __aenter__. Prove it landed:
    result = await client.call_tool("whoami", {})
    assert result.structured_content is not None
    assert "mcp" in result.structured_content["scopes"], result

    # TokenStorage contract: a fresh provider over fresh storage runs the full flow and
    # persists both the issued tokens and the DCR-registered client info.
    storage = InMemoryTokenStorage()
    with anyio.fail_after(5):
        async with connect(auth=_auth_with(storage)) as second:
            await second.call_tool("whoami", {})
    assert storage.tokens is not None
    assert storage.client_info is not None and storage.client_info.client_id is not None
    registered_id = storage.client_info.client_id

    # Token reuse: a fresh Client over the SAME storage sends Bearer on the very first
    # request — no /authorize, no /register. The principal is the one DCR persisted.
    with anyio.fail_after(5):
        async with connect(auth=_auth_with(storage)) as third:
            again = await third.call_tool("whoami", {})
    assert again.structured_content is not None
    assert again.structured_content["client_id"] == registered_id, again


@asynccontextmanager
async def _connect_real(*, auth: AuthBuilder | None = None, **kw: Any) -> AsyncIterator[Client]:
    """Real-socket ``Connect`` for ``__main__``.

    ``Client(url)`` has no ``auth=`` passthrough yet, so build ``httpx.AsyncClient`` →
    ``streamable_http_client`` → ``Client`` by hand and thread the auth onto httpx.
    """
    url = argv_after("--http", default=MCP_URL)
    kw.setdefault("mode", LATEST_MODERN_VERSION)
    async with httpx.AsyncClient() as http:
        http.auth = (auth or build_auth)(http)
        async with Client(streamable_http_client(url, http_client=http), **kw) as c:
            yield c


if __name__ == "__main__":
    run_client(scenario, connect=_connect_real, needs_connect=True)
