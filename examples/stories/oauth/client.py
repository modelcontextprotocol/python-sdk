"""HTTP-only OAuth authorization-code flow; `build_auth` supplies the provider, reconnecting needs `targets`."""

import httpx
from pydantic import AnyUrl

from mcp.client import Client
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata
from stories._harness import TargetFactory, run_client

# The demo AS builds its issuer and PRM `resource` from the same MCP_URL constant, so the story is pinned to :8000.
from stories._shared.auth import MCP_URL, REDIRECT_URI, HeadlessOAuth, InMemoryTokenStorage


def build_auth(http_client: httpx.AsyncClient) -> httpx.Auth:
    """Build an `OAuthClientProvider` that completes the authorize redirect headlessly.

    `Client(url, auth=...)` doesn't exist yet; the harness threads this onto the underlying `httpx.AsyncClient`.
    """
    headless = HeadlessOAuth()
    headless.bind(http_client)
    return OAuthClientProvider(
        server_url=MCP_URL,
        client_metadata=OAuthClientMetadata(
            client_name="oauth-story-client",
            redirect_uris=[AnyUrl(REDIRECT_URI)],
            grant_types=["authorization_code", "refresh_token"],
        ),
        storage=InMemoryTokenStorage(),
        redirect_handler=headless.redirect_handler,
        callback_handler=headless.callback_handler,
    )


async def main(targets: TargetFactory, *, mode: str = "auto") -> None:
    # The first request 401s and the provider transparently walks PRM discovery → AS metadata →
    # DCR → PKCE authorize → token exchange → bearer retry; no UnauthorizedError surfaces here.
    async with Client(targets(), mode=mode) as client:
        first = await client.call_tool("whoami", {})
        assert first.structured_content is not None
        assert "mcp" in first.structured_content["scopes"], first
        registered_id = first.structured_content["client_id"]

    # A Client can't be re-entered after `__aexit__`; reconnecting means a new one. TokenStorage kept
    # the tokens and DCR registration, so this connection sends a bearer token on its first request —
    # and since the demo AS mints a fresh client_id per DCR call, a matching client_id proves reuse.
    async with Client(targets(), mode=mode) as reconnected:
        again = await reconnected.call_tool("whoami", {})
    assert again.structured_content is not None
    assert again.structured_content["client_id"] == registered_id, again


if __name__ == "__main__":
    run_client(main)
