"""HTTP-only OAuth authorization-code flow; `build_auth` supplies the provider, reconnecting needs `targets`."""

import httpx
from pydantic import AnyUrl

from mcp.client import Client
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata
from stories._harness import TargetFactory, run_client

# MCP_URL pins the resource to :8000. The demo AS's own metadata (issuer, PRM `resource`)
# is built from the same constant on the server side, so the whole story is bound to that
# port — run the server on 8000 or both halves of the discovery chain point at the wrong origin.
from stories._shared.auth import MCP_URL, REDIRECT_URI, HeadlessOAuth, InMemoryTokenStorage


def build_auth(http_client: httpx.AsyncClient) -> httpx.Auth:
    """An `OAuthClientProvider` over fresh storage, completing the authorize redirect headlessly.

    `Client(url, auth=...)` doesn't exist yet, so the harness threads this onto the underlying
    `httpx.AsyncClient` and every target `main` receives is already routed through it.
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
    # The target is already authed with build_auth's OAuthClientProvider. The first request to
    # hit the wire 401s, and the provider walks PRM discovery → AS metadata → DCR → PKCE
    # authorize → token exchange → bearer retry before any result reaches this body. No
    # UnauthorizedError ever surfaces.
    async with Client(targets(), mode=mode) as client:
        first = await client.call_tool("whoami", {})
        assert first.structured_content is not None
        assert "mcp" in first.structured_content["scopes"], first
        registered_id = first.structured_content["client_id"]

    # A Client cannot be re-entered after __aexit__; reconnecting means constructing a new one.
    # The provider's TokenStorage persisted both the issued tokens and the DCR registration, so
    # this connection sends `Authorization: Bearer ...` on its very first request — no second
    # /authorize, no second /register. The demo AS mints a fresh client_id per DCR call, so the
    # same principal coming back IS the reuse proof.
    async with Client(targets(), mode=mode) as reconnected:
        again = await reconnected.call_tool("whoami", {})
    assert again.structured_content is not None
    assert again.structured_content["client_id"] == registered_id, again


if __name__ == "__main__":
    run_client(main)
